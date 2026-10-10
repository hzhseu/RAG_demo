"""Optional offline reranking. Original evidence and baseline ranking stay intact."""
import hashlib
import math
import threading
import time

import httpx

from .config import asset
from .index import retrieve, deduplicate_candidates


class RerankError(RuntimeError):
    """Only fixed, non-content-bearing reason codes cross this boundary."""


class RerankCancelled(RuntimeError):
    pass


def check_cancel(cancel, deadline=None):
    if cancel.is_set():
        raise RerankCancelled('任务已取消')
    if deadline is not None and time.monotonic() >= deadline:
        raise RerankError('timeout')


def validate_reranker(cfg, check=lambda: None):
    if not cfg.get('reranker_model'):
        raise RerankError('model_missing')
    path = asset(cfg, 'reranker_model')
    if not path.is_file():
        raise RerankError('model_missing')
    expected = cfg.get('reranker_model_sha256', '')
    if len(expected) != 64:
        raise RerankError('checksum_mismatch')
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            check()
            h.update(block)
    if h.hexdigest() != expected.lower():
        raise RerankError('checksum_mismatch')
    return path


def rank_candidates(candidates, scores, limit=8):
    if len(scores) != len(candidates) or any(type(s) not in (int, float) or not math.isfinite(s) for s in scores):
        raise RerankError('invalid_scores')
    indices = sorted(range(len(scores)), key=lambda i: -scores[i])
    return [{**candidates[i], 'rerank_score': float(scores[i])} for i in indices[:limit]]


def scoring_texts(query, text, tokenize, detokenize, context=8192):
    # Reserve template and special tokens. Truncate only the scoring copy.
    q = tokenize(query)
    q_limit = min(2048, (context - 256) // 2)
    if len(q) > q_limit:
        query = detokenize(q[:q_limit])
        q = tokenize(query)
    tokens = tokenize(text)
    budget = context - len(q) - 256
    if len(tokens) > budget:
        text = detokenize(tokens[:budget])
    return query, text


class Reranker:
    def __init__(self, cfg):
        from .engines import LlamaServer
        self.cfg = cfg
        server_cfg = dict(cfg, threads=cfg.get('reranker_threads', 4),
                          context=cfg.get('reranker_context', 8192))
        self.server = LlamaServer(server_cfg, 'reranker_model', reranking=True)
        self.verified = None

    def stop(self):
        self.server.stop()

    def cancel(self):
        process = self.server.process
        if process and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def score(self, query, candidates, cancel):
        check_cancel(cancel)
        timeout = self.cfg.get('reranker_timeout_seconds', 120)
        context = self.server.cfg['context']
        if type(timeout) not in (float, int) or not math.isfinite(timeout) or timeout <= 0 or type(context) is not int or context < 512:
            raise RerankError('config_invalid')
        deadline = time.monotonic() + timeout
        finished = threading.Event()
        def check():
            check_cancel(cancel, deadline)
        def watchdog():
            while not finished.wait(.05):
                if cancel.is_set() or time.monotonic() >= deadline:
                    self.cancel()
        watcher = threading.Thread(target=watchdog, daemon=True)
        watcher.start()
        try:
            if not self.cfg.get('reranker_model'):
                raise RerankError('model_missing')
            path = asset(self.cfg, 'reranker_model')
            if not path.is_file():
                raise RerankError('model_missing')
            stat = path.stat()
            fingerprint = (str(path.resolve()), stat.st_size, stat.st_mtime_ns, self.cfg.get('reranker_model_sha256'))
            if fingerprint != self.verified:
                self.stop()
                validate_reranker(self.cfg, check)
                self.verified = fingerprint
            check()
            self.server.start()
            check()
            def post(endpoint, body):
                check()
                response = self.server.client.post(endpoint, json=body, timeout=max(.01, deadline-time.monotonic()))
                response.raise_for_status()
                check()
                return response.json()
            def tokenize(text):
                return post('/tokenize', {'content': text, 'add_special': False})['tokens']
            def detokenize(tokens):
                return post('/detokenize', {'tokens': tokens})['content']
            scores = []
            for candidate in candidates:
                q, text = scoring_texts(query, candidate['text'], tokenize, detokenize, context)
                # One pair per request bounds the server batch/context footprint.
                data = post('/v1/rerank', {'query': q, 'documents': [text], 'top_n': 1})
                rows = data.get('results')
                if not isinstance(rows, list) or len(rows) != 1 or rows[0].get('index') != 0:
                    raise RerankError('invalid_scores')
                score = rows[0].get('relevance_score')
                if type(score) not in (float, int) or not math.isfinite(score):
                    raise RerankError('invalid_scores')
                scores.append(score)
            check()
            return scores
        except Exception as exc:
            self.stop()
            check()  # Cancellation and the whole-operation deadline take precedence.
            if isinstance(exc, RerankError):
                raise
            if isinstance(exc, httpx.TimeoutException):
                raise RerankError('timeout') from exc
            if isinstance(exc, (KeyError, TypeError, ValueError, AttributeError)):
                raise RerankError('invalid_scores') from exc
            raise RerankError('unavailable') from exc
        finally:
            finished.set()
            watcher.join(timeout=1)


def retrieve_evidence(root, query, vector, engines, cancel, mode='rerank', progress=lambda: None):
    check_cancel(cancel)
    candidates = retrieve(root, query, vector, 60 if mode == 'rerank' else 8)
    metadata = dict(retrieval_mode='hybrid', rerank_seconds=0.0, rerank_fallback=False, rerank_reason=None)
    if mode != 'rerank':
        return candidates, metadata
    started = time.monotonic()
    try:
        progress()
        cfg = getattr(engines, 'base_cfg', getattr(engines, 'cfg', {}))
        count, final = cfg.get('reranker_candidates', 30), cfg.get('reranker_top_k', 8)
        if type(count) is not int or type(final) is not int or not 1 <= final <= count <= 60:
            raise RerankError('config_invalid')
        unique = deduplicate_candidates(candidates, count)
        check_cancel(cancel)
        if not unique:
            metadata['retrieval_mode'] = 'rerank'
            return [], metadata
        if not hasattr(engines, 'rerank'):
            raise RerankError('model_missing')
        scores = engines.rerank(query, unique, cancel)
        check_cancel(cancel)
        result = rank_candidates(unique, scores, final)
        metadata['retrieval_mode'] = 'rerank'
        return result, metadata
    except RerankError as exc:
        check_cancel(cancel)
        metadata.update(rerank_fallback=True, rerank_reason=str(exc))
        return candidates[:8], metadata
    finally:
        metadata['rerank_seconds'] = round(time.monotonic() - started, 3)

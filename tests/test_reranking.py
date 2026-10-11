import threading

import numpy as np
import pytest

from nordrag.index import create_index, retrieve


@pytest.fixture
def scoring_server(tmp_path):
    """Record the real adapter's HTTP requests; model inference stays deterministic."""
    import hashlib
    import json
    import httpx
    from nordrag.reranking import Reranker
    (tmp_path / 'rank.gguf').write_bytes(b'test')
    ranker = Reranker(dict(root=str(tmp_path), reranker_model='rank.gguf',
                          reranker_model_sha256=hashlib.sha256(b'test').hexdigest()))
    calls = []
    def handler(request):
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path == '/tokenize':
            return httpx.Response(200, json={'tokens': list(map(ord, body['content']))})
        if request.url.path == '/detokenize':
            return httpx.Response(200, json={'content': ''.join(map(chr, body['tokens']))})
        assert request.url.path == '/v1/rerank'
        return httpx.Response(200, json={'results': [{'index': 0,
            'relevance_score': len(body['documents'][0]) / 10000}]})
    with httpx.Client(transport=httpx.MockTransport(handler), base_url='http://test') as client:
        ranker.server.start = lambda: None
        ranker.server.stop = lambda: None
        ranker.server.client = client
        yield ranker, calls


def test_scoring_prepares_query_once_for_sixteen_documents(scoring_server):
    ranker, calls = scoring_server
    candidates = [chunk(i, 'D' * (i + 1), page=i + 1) for i in range(16)]
    scores = ranker.score('question', candidates, threading.Event())
    assert scores == [(i + 1) / 10000 for i in range(16)]
    assert sum(path == '/tokenize' and body['content'] == 'question' for path, body in calls) == 1
    assert len(calls) == 33


def test_scoring_reuses_truncated_query_and_identical_inputs_only_within_request(scoring_server):
    ranker, calls = scoring_server
    ranker.server.cfg['context'] = 512
    query = 'Q' * 300
    candidates = [chunk(0, 'D' * 1000, page=1), chunk(1, 'D' * 1000, page=2),
                  chunk(2, 'D' * 1000 + 'different tail', page=3)]
    from copy import deepcopy
    original = deepcopy(candidates)
    for attempt in range(2):
        start = len(calls)
        scores = ranker.score(query, candidates, threading.Event())
        batch = calls[start:]
        requests = [body for path, body in batch if path == '/v1/rerank']
        assert len(requests) == 1
        assert requests[0]['query'] == 'Q' * 128
        assert requests[0]['documents'] == ['D' * 128]
        assert scores == [.0128] * 3
        assert sum(path == '/tokenize' and body['content'] == query for path, body in batch) == 1
        assert sum(path == '/tokenize' and body['content'] == 'D' * 1000 for path, body in batch) == 1
        assert candidates == original


def chunk(i, text, doc='a', page=1, kind='text'):
    return dict(id=str(i), doc_id=doc, page=page, kind=kind, text=text)


def test_candidates_deduplicate_only_identical_same_source(tmp_path):
    from nordrag.index import retrieve_candidates
    chunks = [chunk(0, 'Alpha  2025 120 EUR'), chunk(1, 'Alpha\n2025 120 EUR'),
              chunk(2, 'Alpha 2024 120 EUR'), chunk(3, 'Alpha 2025 120 EUR', page=2),
              chunk(4, 'Alpha 2025 120 EUR', doc='b'),
              chunk(5, 'Alpha 2025 120 EUR', kind='table')]
    create_index(tmp_path, chunks, [[1., 0.]] * len(chunks))
    hits = retrieve_candidates(tmp_path, 'Alpha', [1., 0.])
    assert [c['id'] for c in hits] == ['0', '2', '3', '4', '5']
    assert len(retrieve(tmp_path, 'Alpha', [1., 0.])) == 6


def test_rerank_order_is_stable_and_preserves_original_evidence():
    from nordrag.reranking import rank_candidates
    source = [dict(chunk(i, f'Value {i} EUR'), score=.02, similarity=.8) for i in range(4)]
    result = rank_candidates(source, [.1, .9, .9, .2], limit=3)
    assert [c['id'] for c in result] == ['1', '2', '3']
    assert result[0]['text'] == source[1]['text']
    assert result[0]['score'] == .02 and result[0]['similarity'] == .8
    assert result[0]['rerank_score'] == .9
    assert 'rerank_score' not in source[1]


@pytest.mark.parametrize('scores', [[.1], [.1, float('nan')], [.1, float('inf')], [.1, '1'], [.1, True]])
def test_invalid_scores_are_rejected(scores):
    from nordrag.reranking import rank_candidates, RerankError
    with pytest.raises(RerankError, match='invalid_scores'):
        rank_candidates([chunk(0, 'a'), chunk(1, 'b')], scores)


def test_retrieval_fallback_matches_baseline_exactly(tmp_path):
    from nordrag.reranking import retrieve_evidence, RerankError
    chunks = [chunk(i, f'Alpha {i}') for i in range(12)]
    create_index(tmp_path, chunks, [[1., 0.]] * len(chunks))
    class Broken:
        cfg = {}
        def rerank(self, *args): raise RerankError('timeout')
    expected = retrieve(tmp_path, 'Alpha', [1., 0.])
    hits, meta = retrieve_evidence(tmp_path, 'Alpha', [1., 0.], Broken(), threading.Event())
    assert hits == expected
    assert meta['retrieval_mode'] == 'hybrid'
    assert meta['rerank_fallback'] and meta['rerank_reason'] == 'timeout'


def test_cancel_never_falls_back(tmp_path):
    from nordrag.reranking import retrieve_evidence, RerankCancelled
    event = threading.Event(); event.set()
    with pytest.raises(RerankCancelled):
        retrieve_evidence(tmp_path, 'q', [1., 0.], None, event)


def test_hybrid_mode_does_not_touch_reranker(tmp_path):
    from nordrag.reranking import retrieve_evidence
    create_index(tmp_path, [chunk(0, 'Alpha')], [[1., 0.]])
    hits, meta = retrieve_evidence(tmp_path, 'Alpha', [1., 0.], None, threading.Event(), 'hybrid')
    assert hits == retrieve(tmp_path, 'Alpha', [1., 0.])
    assert meta['retrieval_mode'] == 'hybrid' and not meta['rerank_fallback']


def test_missing_and_bad_model_hash(tmp_path):
    from nordrag.reranking import validate_reranker, RerankError
    cfg = dict(root=str(tmp_path), reranker_model='rank.gguf', reranker_model_sha256='a'*64)
    with pytest.raises(RerankError, match='model_missing'): validate_reranker(cfg)
    (tmp_path / 'rank.gguf').write_bytes(b'wrong weights')
    with pytest.raises(RerankError, match='checksum_mismatch'): validate_reranker(cfg)


def test_truncation_only_changes_scoring_copy():
    from nordrag.reranking import scoring_texts
    query, doc = 'Q' * 3000, 'D' * 10000
    q, d = scoring_texts(query, doc, list, ''.join, 8192)
    assert len(q) <= 2048 and len(q) + len(d) + 256 <= 8192
    assert query == 'Q' * 3000 and doc == 'D' * 10000


def test_candidate_limit_applies_after_deduplication(tmp_path):
    from nordrag.index import retrieve_candidates
    chunks = [chunk(i, 'Alpha' if i < 3 else f'Alpha {i}') for i in range(40)]
    create_index(tmp_path, chunks, [[1., 0.]] * len(chunks))
    hits = retrieve_candidates(tmp_path, 'Alpha', [1., 0.], limit=4)
    assert len(hits) == 4
    assert len({' '.join(c['text'].split()) for c in hits}) == 4


@pytest.mark.parametrize('cancelled', [False, True])
def test_watchdog_interrupts_blocked_start_and_never_falls_back_on_cancel(tmp_path, cancelled):
    import hashlib
    import time
    from nordrag.reranking import Reranker, RerankCancelled, RerankError
    path = tmp_path/'rank.gguf'; path.write_bytes(b'test')
    cfg = dict(root=str(tmp_path), reranker_model='rank.gguf',
               reranker_model_sha256=hashlib.sha256(b'test').hexdigest(),
               reranker_timeout_seconds=.15 if not cancelled else 10)
    ranker = Reranker(cfg)
    killed = threading.Event()
    event = threading.Event()
    class Process:
        def poll(self): return 1 if killed.is_set() else None
        def terminate(self): killed.set()
    class Server:
        cfg = {'context':8192}
        process = None
        def stop(self): pass
        def start(self):
            self.process = Process()
            if cancelled: event.set()
            assert killed.wait(1), 'watchdog did not stop owned process'
            raise RuntimeError('startup interrupted')
    ranker.server = Server()
    start = time.monotonic()
    with pytest.raises(RerankCancelled if cancelled else RerankError, match='任务已取消' if cancelled else 'timeout'):
        ranker.score('q', [chunk(0,'answer')], event)
    assert killed.is_set() and time.monotonic()-start < 1


@pytest.mark.parametrize('data', [{'results':[]}, {'results':[{'index':9,'relevance_score':.5}]}, {'results':[{'index':0,'relevance_score':float('nan')}]}])
def test_runtime_rejects_malformed_score_responses(tmp_path, data):
    import hashlib
    import httpx
    from nordrag.reranking import Reranker, RerankError
    (tmp_path/'rank.gguf').write_bytes(b'test')
    ranker=Reranker(dict(root=str(tmp_path), reranker_model='rank.gguf', reranker_model_sha256=hashlib.sha256(b'test').hexdigest()))
    def handler(request):
        if request.url.path == '/tokenize': return httpx.Response(200,json={'tokens':[1]})
        # NaN JSON is intentionally malformed model output.
        import json
        return httpx.Response(200,text=json.dumps(data))
    client=httpx.Client(transport=httpx.MockTransport(handler),base_url='http://test')
    ranker.server.start=lambda:None
    ranker.server.stop=lambda:None
    ranker.server.client=client
    try:
        with pytest.raises(RerankError,match='invalid_scores'): ranker.score('q',[chunk(0,'a')],threading.Event())
    finally: client.close()

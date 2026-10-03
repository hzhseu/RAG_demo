import json
import hashlib
import shutil
import tempfile
import time
from pathlib import Path
import numpy as np
from .parsing import scan, parse_pptx, chunk_pages, PARSER_VERSION, CHUNK_MAX_CHARS
from .package import seal
from .index import create_index
from .util import read_json, write_json, digest
from .diagnostics import describe_error, ComponentUnavailableError


class BuildError(RuntimeError):
    def __init__(self, message, *, report=None, report_path=None):
        super().__init__(message)
        self.report = report
        self.report_path = report_path


def check_cancel(cancel):
    if cancel.is_set():
        raise BuildError("任务已取消")


def record_document_failure(report, doc, stage, error, folder, progress):
    # Storage/resource failures affect the whole build. A vanished/unreadable
    # source file is the exception: it belongs to this document alone.
    source_error = (isinstance(error, (FileNotFoundError, PermissionError))
                    and error.filename and Path(error.filename) == Path(doc['path']))
    if (isinstance(error, (ComponentUnavailableError, MemoryError))
            or isinstance(error, OSError) and not isinstance(error, TimeoutError) and not source_error):
        raise error
    failure = {"path": doc["relative_path"], "stage": stage,
               "error_type": type(error).__name__, "error": describe_error(error)}
    report['failed'].append(failure)
    progress({'stage': 'failed', 'failure': failure})
    if folder.exists():
        shutil.rmtree(folder)


def build(directory, name, output, cache, engines, cancel, excluded=(), progress=lambda event: None):
    output, cache = Path(output), Path(cache)
    if output.exists():
        raise FileExistsError(f"输出已存在：{output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    report = scan(Path(directory), excluded)
    docs_in = report.pop("documents")
    report.update(status="building", included=[], name=name, total_pages=0,
                  scanned_pages=sum(d["pages"] for d in docs_in))
    report['model'] = getattr(engines,'model_identity',{'id':'default'})
    report_path = output.with_suffix(".report.json")
    stage = 'report'
    try:
        write_json(report_path, report)
        stage = 'scan'
        check_cancel(cancel)
        for failure in report['failed']:
            progress({'stage': 'failed', 'failure': failure})
        if not docs_in:
            raise BuildError("没有可构建的 PPTX，未生成知识库")
        with tempfile.TemporaryDirectory(prefix="build-", dir=cache) as temp:
            root = Path(temp)
            chunks, documents = [], []
            candidates = []
            completed_pages = 0
            for doc in docs_in:
                check_cancel(cancel)
                stage = 'cache'
                key = hashlib.sha256(("parse-v2" + doc["sha256"] + PARSER_VERSION + getattr(engines,"parse_signature",engines.signature)).encode()).hexdigest()
                cached = cache / key
                generated_key = hashlib.sha256((key + engines.signature).encode()).hexdigest()
                generated = cache / 'generation-v2' / (generated_key + '.json')
                folder = root / "documents" / doc["id"]
                try:
                    # Cache is trusted only after verifying every cached file.
                    valid = (cached / "ready.json").exists()
                    if valid:
                        try:
                            valid = all((cached / p).is_file() and digest(cached / p) == sha for p, sha in read_json(cached / "ready.json").items())
                        except (FileNotFoundError, ValueError):
                            valid = False
                    if not valid:
                        if cached.exists():
                            shutil.rmtree(cached)
                        cached.mkdir()
                        stage = 'parse'
                        progress({"stage": "parse", "document": doc["name"], "completed_pages": completed_pages, "total_pages": report["scanned_pages"]})
                        pages = parse_pptx(Path(doc["path"]), engines.ocr, cached / "images")
                        write_json(cached / "pages.json", pages)
                        check_cancel(cancel)
                        stage = 'convert'
                        progress({'stage': stage, 'document': doc['name']})
                        engines.convert(Path(doc["path"]), cached / "preview.pdf", doc["pages"])
                        write_json(cached / "ready.json", {p.relative_to(cached).as_posix(): digest(p) for p in cached.rglob("*") if p.is_file() and p.name != "ready.json"})
                    pages = read_json(cached / "pages.json")
                    stage = 'copy'
                    shutil.copytree(cached, folder, ignore=shutil.ignore_patterns("organization.json", "*.writing"))
                    (folder / "ready.json").unlink(missing_ok=True)
                    shutil.copy2(doc["path"], folder / "source.pptx")
                    stage = 'chunk'
                    doc_chunks = chunk_pages(doc["id"], pages)
                    if not doc_chunks:
                        raise BuildError("未提取到可检索内容，请检查文档")
                    stage = 'organize'
                    progress({"stage": stage, "document": doc["name"]})
                    organized = None
                    if generated.exists():
                        try:
                            record = read_json(generated)
                            value = record['result']
                            if record['sha256'] == hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest():
                                organized = value
                        except (OSError,ValueError,KeyError,TypeError):
                            pass
                    if organized is None:
                        if hasattr(engines, 'organize_with_progress'):
                            def organize_progress(event):
                                nonlocal stage
                                if event['stage'] in ('summarizing', 'classify'):
                                    stage = event['stage']
                                progress({**event, 'document': doc['name']})
                            organized = engines.organize_with_progress(doc_chunks, cancel, organize_progress)
                        else:
                            organized = engines.organize(doc_chunks, cancel)
                        check_cancel(cancel)
                        organized['model'] = getattr(engines,'model_identity',{'id':'default'})
                        write_json(generated, {'result':organized,'sha256':hashlib.sha256(json.dumps(organized,sort_keys=True).encode()).hexdigest()})
                    document = {k: v for k, v in doc.items() if k != "path"} | organized | {"source": f"documents/{doc['id']}/source.pptx", "preview": f"documents/{doc['id']}/preview.pdf"}
                    candidates.append((doc, document, doc_chunks, folder))
                    completed_pages += doc["pages"]
                    progress({"stage": "parsed", "document": doc["name"], "completed_pages": completed_pages, "total_pages": report["scanned_pages"]})
                except Exception as e:
                    check_cancel(cancel)
                    record_document_failure(report, doc, stage, e, folder, progress)
            check_cancel(cancel)
            stage = 'embedding'
            vectors = []
            dimension = None
            for doc, document, doc_chunks, folder in candidates:
                check_cancel(cancel)
                try:
                    doc_vectors = []
                    for start in range(0, len(doc_chunks), 8):
                        check_cancel(cancel)
                        progress({"stage": "embedding", "document": doc['name'], "completed": start, "total": len(doc_chunks)})
                        batch = doc_chunks[start:start + 8]
                        batch_vectors = engines.embed([c["text"] for c in batch])
                        if len(batch_vectors) != len(batch):
                            raise ValueError('文档嵌入向量批次数量与检索片段不匹配')
                        doc_vectors.extend(batch_vectors)
                    check_cancel(cancel)
                    matrix = np.asarray(doc_vectors, dtype=np.float32)
                    if (matrix.ndim != 2 or len(matrix) != len(doc_chunks)
                            or matrix.shape[1] == 0 or not np.isfinite(matrix).all()
                            or np.any(np.linalg.norm(matrix, axis=1) == 0)
                            or dimension is not None and matrix.shape[1] != dimension):
                        raise ValueError('文档嵌入向量数量、维度或数值无效')
                except Exception as e:
                    check_cancel(cancel)
                    record_document_failure(report, doc, stage, e, folder, progress)
                    continue
                dimension = matrix.shape[1]
                vectors.extend(matrix)
                chunks.extend(doc_chunks)
                documents.append(document)
                report['included'].append(doc['relative_path'])
                report['total_pages'] += doc['pages']
            if not documents:
                raise BuildError('所有文档均处理失败，没有可用文档，未生成知识库')
            stage = 'index'
            create_index(root, chunks, vectors)
            write_json(root / "documents.json", documents)
            write_json(root / "chunks.json", chunks)
            check_cancel(cancel)
            report.update(status="complete_with_warnings" if report['failed'] else "complete", chunks=len(chunks), elapsed_seconds=round(time.perf_counter() - started, 2))
            stage = 'report'
            write_json(root / "build-report.json", report)
            processing = {"parser_version": PARSER_VERSION, "chunk_max_chars": CHUNK_MAX_CHARS, "models_and_components": getattr(engines, "identifiers", {"embedding": engines.embedding_id})}
            stage = 'seal'
            m = seal(root, output, {"name": name, "embedding": engines.embedding_id, "parser": PARSER_VERSION, "processing": processing, "engine_signature": engines.signature, "documents": len(documents), "pages": report["total_pages"]})
            report["version"] = m["version"]
            stage = 'report'
            write_json(report_path, report)
    except BaseException as e:
        report.update(status="cancelled" if cancel.is_set() or isinstance(e, KeyboardInterrupt) else "failed", error=describe_error(e), stage=stage, error_type=type(e).__name__, elapsed_seconds=round(time.perf_counter() - started, 2))
        saved_path = None
        try:
            write_json(report_path, report)
            saved_path = report_path.resolve()
        except OSError as report_error:
            report['report_error'] = describe_error(report_error)
        raise BuildError(str(e) or describe_error(e), report=report, report_path=saved_path) from e
    progress({"stage": "complete", "output": str(output), "status": report['status']})
    return report

import hashlib
import json
import shutil
import tempfile
import time
from pathlib import Path
from .parsing import scan, parse_pptx, chunk_pages, PARSER_VERSION, CHUNK_MAX_CHARS
from .package import seal
from .index import create_index
from .util import read_json, write_json, digest
from .diagnostics import describe_error


class BuildError(RuntimeError):
    def __init__(self, message, *, report=None, report_path=None):
        super().__init__(message)
        self.report = report
        self.report_path = report_path


def check_cancel(cancel):
    if cancel.is_set():
        raise BuildError("任务已取消")


def build(directory, name, output, cache, engines, cancel, excluded=(), progress=lambda event: None):
    output, cache = Path(output), Path(cache)
    if output.exists():
        raise FileExistsError(f"输出已存在：{output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    report = scan(Path(directory), excluded)
    docs_in = report.pop("documents")
    report.update(status="building", included=[], name=name, total_pages=sum(d["pages"] for d in docs_in))
    report_path = output.with_suffix(".report.json")
    write_json(report_path, report)
    stage = 'scan'
    try:
        check_cancel(cancel)
        if not docs_in:
            raise BuildError("没有可构建的 PPTX")
        with tempfile.TemporaryDirectory(prefix="build-", dir=cache) as temp:
            root = Path(temp)
            chunks, documents = [], []
            completed_pages = 0
            for doc in docs_in:
                check_cancel(cancel)
                stage = 'cache'
                key = hashlib.sha256((doc["sha256"] + PARSER_VERSION + engines.signature).encode()).hexdigest()
                cached = cache / key
                try:
                    # Cache is trusted only after verifying every cached file.
                    valid = (cached / "ready.json").exists()
                    if valid:
                        try:
                            valid = all((cached / p).is_file() and digest(cached / p) == sha for p, sha in read_json(cached / "ready.json").items())
                        except (OSError, ValueError):
                            valid = False
                    if not valid:
                        if cached.exists():
                            shutil.rmtree(cached)
                        cached.mkdir()
                        stage = 'parse'
                        progress({"stage": "parse", "document": doc["name"], "completed_pages": completed_pages, "total_pages": report["total_pages"]})
                        pages = parse_pptx(Path(doc["path"]), engines.ocr, cached / "images")
                        write_json(cached / "pages.json", pages)
                        check_cancel(cancel)
                        stage = 'convert'
                        progress({'stage': stage, 'document': doc['name']})
                        engines.convert(Path(doc["path"]), cached / "preview.pdf", doc["pages"])
                        write_json(cached / "ready.json", {p.relative_to(cached).as_posix(): digest(p) for p in cached.rglob("*") if p.is_file() and p.name != "ready.json"})
                    pages = read_json(cached / "pages.json")
                    stage = 'copy'
                    folder = root / "documents" / doc["id"]
                    shutil.copytree(cached, folder, ignore=shutil.ignore_patterns("organization.json", "*.writing"))
                    (folder / "ready.json").unlink(missing_ok=True)
                    shutil.copy2(doc["path"], folder / "source.pptx")
                    stage = 'chunk'
                    doc_chunks = chunk_pages(doc["id"], pages)
                    if not doc_chunks:
                        raise BuildError("未提取到可检索内容，请检查文档")
                    stage = 'organize'
                    progress({"stage": stage, "document": doc["name"]})
                    if (cached / "organization.json").exists():
                        organized = read_json(cached / "organization.json")
                    else:
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
                        write_json(cached / "organization.json", organized)
                        write_json(cached / "ready.json", {p.relative_to(cached).as_posix(): digest(p) for p in cached.rglob("*") if p.is_file() and p.name != "ready.json" and not p.name.endswith(".writing")})
                    documents.append({k: v for k, v in doc.items() if k != "path"} | organized | {"source": f"documents/{doc['id']}/source.pptx", "preview": f"documents/{doc['id']}/preview.pdf"})
                    chunks.extend(doc_chunks)
                    report["included"].append(doc["relative_path"])
                    completed_pages += doc["pages"]
                    progress({"stage": "parsed", "document": doc["name"], "completed_pages": completed_pages, "total_pages": report["total_pages"]})
                except Exception as e:
                    check_cancel(cancel)
                    failure = {"path": doc["relative_path"], "stage": stage, "error_type": type(e).__name__, "error": describe_error(e)}
                    report["failed"].append(failure)
                    progress({'stage': 'failed', 'failure': failure})
            if report["failed"]:
                stage = 'documents'
                raise BuildError("存在失败文件；请修复重试或使用 --exclude 明确排除")
            check_cancel(cancel)
            stage = 'embedding'
            vectors = []
            for start in range(0, len(chunks), 8):
                check_cancel(cancel)
                progress({"stage": "embedding", "completed": start, "total": len(chunks)})
                vectors.extend(engines.embed([c["text"] for c in chunks[start:start + 8]]))
            stage = 'index'
            create_index(root, chunks, vectors)
            write_json(root / "documents.json", documents)
            write_json(root / "chunks.json", chunks)
            check_cancel(cancel)
            report.update(status="complete", chunks=len(chunks), elapsed_seconds=round(time.perf_counter() - started, 2))
            write_json(root / "build-report.json", report)
            processing = {"parser_version": PARSER_VERSION, "chunk_max_chars": CHUNK_MAX_CHARS, "models_and_components": getattr(engines, "identifiers", {"embedding": engines.embedding_id})}
            stage = 'seal'
            m = seal(root, output, {"name": name, "embedding": engines.embedding_id, "parser": PARSER_VERSION, "processing": processing, "engine_signature": engines.signature, "documents": len(documents), "pages": report["total_pages"]})
            report["version"] = m["version"]
    except BaseException as e:
        report.update(status="cancelled" if cancel.is_set() or isinstance(e, KeyboardInterrupt) else "failed", error=describe_error(e), stage=stage, error_type=type(e).__name__, elapsed_seconds=round(time.perf_counter() - started, 2))
        saved_path = None
        try:
            write_json(report_path, report)
            saved_path = report_path.resolve()
        except OSError as report_error:
            report['report_error'] = describe_error(report_error)
        raise BuildError(str(e) or describe_error(e), report=report, report_path=saved_path) from e
    else:
        write_json(report_path, report)
    progress({"stage": "complete", "output": str(output)})
    return report

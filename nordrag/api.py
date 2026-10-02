import asyncio
import json
import queue
import re
import secrets
import shutil
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import __version__
from .util import read_json, write_json
from .index import retrieve, all_chunks
from .generation import prepare_messages, checked_answer, summarize_topic
from .package import export_package
from .operations import OperationLock
from .logging_utils import logger


class ChatRequest(BaseModel):
    session_id: str
    question: str = Field(min_length=1, max_length=2000)


class TopicRequest(BaseModel):
    session_id: str
    document_ids: list[str] = Field(min_length=1, max_length=100)


class Labels(BaseModel):
    category: str = Field(max_length=80)
    tags: list[str] = Field(max_length=20)


class OwnedFileResponse(FileResponse):
    def __init__(self, *args, release, **kwargs):
        super().__init__(*args, **kwargs)
        self.release = release

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.release()


def create_app(root: Path, manifest, engines, home: Path, token=None, static_dir=None):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    token = token or secrets.token_urlsafe(32)
    app.state.token = token
    home.mkdir(parents=True, exist_ok=True)
    session_dir = home / "sessions"
    session_dir.mkdir(exist_ok=True)
    docs = read_json(root / "documents.json")
    docs_by_id = {d["id"]: d for d in docs}
    edits = home / "labels" / f"{manifest['version']}.json"
    if edits.exists():
        saved = {d["id"]: d for d in read_json(edits)}
        for d in docs:
            if d["id"] in saved:
                d.update({k: saved[d["id"]][k] for k in ("category", "tags")})
    busy = OperationLock(home)
    state_lock = threading.RLock()
    jobs = {}
    app.state.jobs = jobs

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        origin = request.headers.get("origin")
        host = request.url.hostname
        if host not in ("127.0.0.1", "localhost", "testserver") or (origin and urlparse(origin).netloc != request.headers.get("host")):
            return JSONResponse({"detail": "仅允许本机同源访问"}, status_code=403)
        if request.url.path.startswith("/api/"):
            supplied = request.headers.get("X-Nord-Token", "")
            if not secrets.compare_digest(supplied, token):
                return JSONResponse({"detail": "会话令牌无效，请从启动程序打开"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    def session_path(sid):
        if not re.fullmatch(r"[a-f0-9]{32}", sid):
            raise HTTPException(404, "会话不存在")
        return session_dir / f"{sid}.json"

    def get_session(sid):
        p = session_path(sid)
        if not p.exists():
            raise HTTPException(404, "会话不存在")
        value = read_json(p)
        if value["knowledge_version"] != manifest["version"]:
            raise HTTPException(409, "该会话属于其他知识库，请打开对应知识库")
        return value

    def attach_names(chunks):
        return [{**c, "doc_name": docs_by_id[c["doc_id"]]["name"]} for c in chunks]

    @app.get("/api/status")
    def status():
        return {"app_version": __version__, "knowledge": manifest, "model": "Qwen3-4B-Instruct-2507 · CPU", "busy": busy.locked()}

    @app.get("/api/documents")
    def documents():
        with state_lock:
            return list(docs)

    @app.patch("/api/documents/{doc_id}")
    def labels(doc_id: str, body: Labels):
        if doc_id not in docs_by_id:
            raise HTTPException(404, "文档不存在")
        if any(len(t) > 40 for t in body.tags):
            raise HTTPException(422, "单个标签不能超过40字符")
        with state_lock:
            docs_by_id[doc_id].update(category=body.category, tags=list(dict.fromkeys(body.tags)))
            write_json(edits, docs)
        return {"saved": True, "export_required": True}

    @app.get("/api/documents/{doc_id}/preview")
    def preview(doc_id: str):
        if doc_id not in docs_by_id:
            raise HTTPException(404, "文档不存在")
        path = (root / docs_by_id[doc_id]["preview"]).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise HTTPException(404, "预览不存在")
        return FileResponse(path, media_type="application/pdf")

    @app.post("/api/export")
    def export():
        if not busy.acquire(blocking=False):
            raise HTTPException(409, "请等待当前任务完成")
        try:
            folder = home / "exports"
            folder.mkdir(exist_ok=True)
            output = folder / f"knowledge-{uuid.uuid4().hex}.ragkb"
            with state_lock:
                export_package(root, output, docs)
            return OwnedFileResponse(output, filename="knowledge.ragkb", media_type="application/octet-stream", release=busy.release)
        except BaseException:
            busy.release()
            raise

    @app.post("/api/sessions")
    def new_session():
        sid = uuid.uuid4().hex
        data = {"id": sid, "knowledge_version": manifest["version"], "title": "新对话", "created_at": time.time(), "messages": []}
        with state_lock:
            write_json(session_path(sid), data)
        return data

    @app.get("/api/sessions")
    def sessions():
        with state_lock:
            result = [read_json(p) for p in session_dir.glob("*.json")]
        return [{k: v for k, v in s.items() if k != "messages"} for s in sorted(result, key=lambda s: s["created_at"], reverse=True) if s["knowledge_version"] == manifest["version"]]

    @app.get("/api/sessions/{sid}")
    def session(sid: str):
        with state_lock:
            return get_session(sid)

    @app.delete("/api/sessions/{sid}")
    def delete_session(sid: str):
        if busy.locked():
            raise HTTPException(409, "请先停止生成")
        with state_lock:
            get_session(sid)
            session_path(sid).unlink()
        return {"deleted": True}

    @app.post("/api/cache/clear")
    def clear_cache():
        if not busy.acquire(blocking=False):
            raise HTTPException(409, "请等待当前任务完成")
        try:
            for name in ("cache", "exports"):
                target = home / name
                if target.exists():
                    shutil.rmtree(target)
            return {"cleared": True}
        finally:
            busy.release()

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        with state_lock:
            event = jobs.get(job_id)
            if not event:
                raise HTTPException(404, "任务已结束")
            event.set()
        return {"cancelled": True}

    def start_generation(sid, question, selected=None):
        with state_lock:
            conversation = get_session(sid)
        if not busy.acquire(blocking=False):
            raise HTTPException(409, "已有生成任务，请等待或停止")
        logger.info('generation_started kind=%s', 'topic' if selected else 'chat')
        event = threading.Event()
        jid = uuid.uuid4().hex
        messages_queue = queue.Queue()
        with state_lock:
            jobs[jid] = event

        def send(kind, **data):
            messages_queue.put({"type": kind, **data})

        def worker():
            started = time.perf_counter()
            first_token = None
            finished = threading.Event()
            def watch():
                while not finished.wait(.1):
                    if event.is_set():
                        engines.cancel()
            watcher = threading.Thread(target=watch, daemon=True)
            watcher.start()
            def check():
                if event.is_set():
                    raise RuntimeError("任务已取消")
            def count(text):
                check()
                return engines.count(text)
            try:
                check()
                send("job", id=jid)
                send("status", message="正在整理证据…" if selected else "正在检索知识库…")
                if selected:
                    evidence = attach_names([c for c in all_chunks(root) if c["doc_id"] in selected])
                    # Batches cover every selected document, preserving page-level sources.
                    summary = summarize_topic(engines, evidence, event, lambda e: send("progress", **e))
                    answer, citations = summary["summary"], summary["citations"]
                    valid = True
                    send("evidence", citations=citations)
                    send("delta", text=answer)
                else:
                    history = conversation["messages"]
                    # Include previous user question to resolve short follow-up questions.
                    previous = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
                    search_query = (previous[-400:] + "\n" + question) if previous and len(question) < 80 else question
                    vector = engines.embed([search_query], query=True)[0]
                    check()
                    evidence = attach_names(retrieve(root, search_query, vector))
                    prompt, citations = prepare_messages(question, evidence, history, count)
                    check()
                    send("evidence", citations=citations)
                    answer = ""
                    if citations and not event.is_set():
                        for part in engines.stream(prompt, event):
                            if event.is_set():
                                break
                            if part and first_token is None:
                                first_token = time.perf_counter() - started
                            answer += part
                            send("delta", text=part)
                        answer, valid = checked_answer(answer, citations)
                    else:
                        answer, valid = "没有可用证据，无法回答。 / No evidence available.", False
                if event.is_set():
                    logger.info('generation_cancelled')
                    send("cancelled")
                    return
                conversation["title"] = conversation["title"] if conversation["messages"] else question[:40]
                conversation["messages"].extend([{"role": "user", "content": question}, {"role": "assistant", "content": answer, "citations": citations, "supported": valid, "knowledge_version": manifest["version"]}])
                with state_lock:
                    write_json(session_path(sid), conversation)
                send("done", text=answer, supported=valid, citations=citations, elapsed_seconds=round(time.perf_counter()-started, 2), first_token_seconds=first_token)
                logger.info('generation_completed supported=%s seconds=%.2f', valid, time.perf_counter()-started)
            except Exception as e:
                logger.warning('generation_interrupted cancelled=%s exception_type=%s', event.is_set(), type(e).__name__)
                send("cancelled" if event.is_set() else "error", message=str(e))
            finally:
                finished.set()
                watcher.join(timeout=1)
                with state_lock:
                    jobs.pop(jid, None)
                busy.release()
                messages_queue.put(None)

        threading.Thread(target=worker, daemon=True).start()

        async def events():
            try:
                while True:
                    try:
                        item = messages_queue.get_nowait()
                    except queue.Empty:
                        await asyncio.sleep(0.05)
                        continue
                    if item is None:
                        break
                    yield "data: " + json.dumps(item, ensure_ascii=False) + "\n\n"
            finally:
                event.set()
        return StreamingResponse(events(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    @app.post("/api/chat")
    def chat(body: ChatRequest):
        if not body.question.strip():
            raise HTTPException(422, "问题不能为空")
        return start_generation(body.session_id, body.question.strip())

    @app.post("/api/topic")
    def topic(body: TopicRequest):
        if any(d not in docs_by_id for d in body.document_ids):
            raise HTTPException(404, "所选文档不存在")
        return start_generation(body.session_id, "专题总结：" + "、".join(docs_by_id[d]["name"] for d in body.document_ids), set(body.document_ids))

    if static_dir and Path(static_dir).exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    return app

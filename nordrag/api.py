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
from typing import Literal
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import __version__
from .util import read_json, write_json
from .index import retrieve, all_chunks
from .generation import prepare_messages, checked_answer, summarize_topic
from .catalog import is_catalog_count_question, catalog_count_answer
from .package import export_package
from .operations import OperationLock
from .chat_models import identity
from .logging_utils import logger


class SessionRequest(BaseModel):
    mode: Literal['knowledge', 'advanced'] = 'knowledge'


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


def create_knowledge_app(root: Path, manifest, engines, home: Path, token=None, static_dir=None, operation_lock=None):
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
    busy = operation_lock or OperationLock(home)
    state_lock = threading.RLock()
    jobs = {}
    app.state.jobs = jobs
    app.state.models = None
    app.state.retain_worker = lambda: None
    app.state.release_worker = lambda: None

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
        legacy={'id':'default','name':'Qwen3-4B-Instruct-2507','sha256':'3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597','generation':{'temperature':.1},'legacy_inferred':True}
        value.setdefault('model',legacy)
        value.setdefault('mode', 'knowledge')
        for message in value['messages']:
            if message.get('role')=='assistant':message.setdefault('model',value['model'])
        return value

    def current_identity():
        return getattr(engines,'model_identity', {'id':'default','name':'Qwen3-4B-Instruct-2507'})

    def check_binding(saved, current):
        fields=('id','sha256') if saved.get('legacy_inferred') else ('id','sha256','generation','chat_template_kwargs','context','engine_sha256')
        if any(key in saved and key in current and saved[key] != current[key] for key in fields):
            raise HTTPException(409,'会话绑定的模型文件或生成配置已改变，请恢复原配置或新建对话')

    def check_model(request):
        if app.state.models:
            app.state.models.check_sequence(request.headers.get('X-Model-Sequence'))

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

    def new_session(mode='knowledge'):
        sid = uuid.uuid4().hex
        data = {"id": sid, "knowledge_version": manifest["version"], "title": "新对话", "created_at": time.time(), "messages": [], "model": current_identity(), "mode": mode}
        with state_lock:
            write_json(session_path(sid), data)
        return data

    app.state.new_session = new_session

    @app.post('/api/sessions')
    def create_session(request: Request, body: SessionRequest | None = None):
        if not busy.acquire(blocking=False):raise HTTPException(409,'请等待当前任务完成')
        try:
            check_model(request)
            return new_session(body.mode if body else 'knowledge')
        finally:busy.release()

    @app.get("/api/sessions")
    def sessions():
        with state_lock:
            result = [read_json(p) for p in session_dir.glob("*.json")]
        return [{**{k: v for k, v in s.items() if k != "messages"}, 'mode': s.get('mode', 'knowledge')} for s in sorted(result, key=lambda s: s["created_at"], reverse=True) if s["knowledge_version"] == manifest["version"]]

    @app.get("/api/sessions/{sid}")
    def session(sid: str):
        with state_lock:
            return get_session(sid)

    @app.post('/api/sessions/{sid}/activate')
    def activate_session(sid: str, request: Request):
        if not busy.acquire(blocking=False):
            raise HTTPException(409,'请等待当前任务完成')
        try:
            check_model(request)
            conversation=get_session(sid)
            if app.state.models:
                entry=app.state.models.models.get(conversation['model']['id'])
                if not entry:raise HTTPException(409,'此会话绑定的模型已不在列表中')
                check_binding(conversation['model'],identity(entry['cfg']))
            if app.state.models and (conversation['model']['id'] != current_identity()['id'] or app.state.models.state == 'error'):
                app.state.models.switch(conversation['model']['id'],request.headers.get('X-Model-Sequence'),locked=True)
            return conversation
        finally:busy.release()

    @app.get('/api/sessions/{sid}/export')
    def export_session(sid: str):
        return JSONResponse(get_session(sid), headers={'Content-Disposition':f'attachment; filename="conversation-{sid}.json"'})

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

    def start_generation(sid, question, selected=None, request=None):
        catalog_query = not selected and is_catalog_count_question(question)
        with state_lock:
            conversation = get_session(sid)
        mode = conversation['mode']
        if selected and mode != 'knowledge':
            raise HTTPException(409, '专题总结需要知识问答会话，请新建知识问答后重试')
        if not busy.acquire(blocking=False):
            raise HTTPException(409, "已有生成任务，请等待或停止")
        try:
            if request:check_model(request)
            check_binding(conversation['model'],current_identity())
            if conversation['model']['id'] != current_identity()['id']:
                raise HTTPException(409,'此会话绑定其他模型，请重新选择该会话后继续')
            if app.state.models and app.state.models.state == 'error':
                raise HTTPException(409,'模型尚未就绪，请重新选择回答模型')
        except BaseException:
            busy.release()
            raise
        model_identity = current_identity()
        logger.info('generation_started kind=%s', 'topic' if selected else 'catalog' if catalog_query else 'chat')
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
            answer_source = None
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
                send("status", message="正在统计知识库目录…" if catalog_query else "正在整理证据…" if selected else "正在检索知识库…")
                if catalog_query:
                    answer, answer_source = catalog_count_answer(docs, manifest['version'], question)
                    citations, valid = [], True
                    first_token = time.perf_counter() - started
                    send("evidence", citations=citations)
                    send("delta", text=answer)
                elif selected:
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
                    prompt, citations = prepare_messages(question, evidence, history, count, budget=min(6500,int(getattr(engines,'cfg',{}).get('context',8192))-1024), mode=mode)
                    check()
                    send("evidence", citations=citations)
                    answer = ""
                    if (citations or mode == 'advanced') and not event.is_set():
                        for part in engines.stream(prompt, event):
                            if event.is_set():
                                break
                            if part and first_token is None:
                                first_token = time.perf_counter() - started
                            answer += part
                            send("delta", text=part)
                        answer, valid = checked_answer(answer, citations, mode=mode)
                    else:
                        answer, valid = "没有可用证据，无法回答。 / No evidence available.", False
                if event.is_set():
                    logger.info('generation_cancelled')
                    send("cancelled")
                    return
                conversation["title"] = conversation["title"] if conversation["messages"] else question[:40]
                supported = valid and (mode == 'knowledge' or catalog_query)
                conversation["messages"].extend([{"role": "user", "content": question}, {"role": "assistant", "content": answer, "citations": citations, "supported": supported, "citation_valid": valid, "mode": mode, "knowledge_version": manifest["version"], "model": model_identity, "answer_source": answer_source}])
                with state_lock:
                    write_json(session_path(sid), conversation)
                send("done", text=answer, model=model_identity, supported=supported, citation_valid=valid, mode=mode, citations=citations, answer_source=answer_source, elapsed_seconds=round(time.perf_counter()-started, 2), first_token_seconds=first_token)
                logger.info('generation_completed mode=%s supported=%s seconds=%.2f', mode, supported, time.perf_counter()-started)
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
                app.state.release_worker()

        app.state.retain_worker()
        try:
            threading.Thread(target=worker, daemon=True).start()
        except BaseException:
            with state_lock:
                jobs.pop(jid, None)
            busy.release()
            app.state.release_worker()
            raise

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
    def chat(body: ChatRequest, request: Request):
        if not body.question.strip():
            raise HTTPException(422, "问题不能为空")
        return start_generation(body.session_id, body.question.strip(), request=request)

    @app.post("/api/topic")
    def topic(body: TopicRequest, request: Request):
        if any(d not in docs_by_id for d in body.document_ids):
            raise HTTPException(404, "所选文档不存在")
        return start_generation(body.session_id, "专题总结：" + "、".join(docs_by_id[d]["name"] for d in body.document_ids), set(body.document_ids), request=request)

    if static_dir and Path(static_dir).exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    return app


def create_app(root: Path | None, manifest, engines, home: Path, token=None, static_dir=None, *, picker=None):
    """Stable authenticated gateway; knowledge-scoped handlers keep immutable contexts."""
    from contextlib import asynccontextmanager
    from fastapi.responses import Response
    from .knowledge import KnowledgeManager

    token = token or secrets.token_urlsafe(32)
    manager = KnowledgeManager(engines, home,
        lambda r, m, lock: create_knowledge_app(r, m, engines, home, token, operation_lock=lock), picker)
    from .model_manager import ModelManager
    models = ModelManager(engines, home, manager.busy) if hasattr(engines,'base_cfg') else None
    original_factory = manager.factory
    def factory(r,m,lock):
        scoped=original_factory(r,m,lock)
        scoped.state.models=models
        return scoped
    manager.factory=factory
    if root is not None:
        manager.adopt(root, manifest)

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            manager.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.token = token
    app.state.knowledge = manager
    app.state.models = models

    @app.middleware('http')
    async def authenticate(request: Request, call_next):
        origin = request.headers.get('origin')
        if request.url.hostname not in ('127.0.0.1', 'localhost', 'testserver') or (origin and urlparse(origin).netloc != request.headers.get('host')):
            return JSONResponse({'detail': '仅允许本机同源访问'}, status_code=403)
        if request.url.path.startswith('/api/') and not secrets.compare_digest(request.headers.get('X-Nord-Token', ''), token):
            return JSONResponse({'detail': '会话令牌无效，请从启动程序打开'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        detail = exc.detail
        if isinstance(detail, dict):
            return JSONResponse({'detail': detail['message'], 'code': detail['code']}, status_code=exc.status_code)
        return JSONResponse({'detail': detail}, status_code=exc.status_code)

    @app.get('/api/status')
    def status():
        return {'app_version': __version__, 'model': 'Qwen3-4B-Instruct-2507 · CPU', **manager.status(), **(app.state.models.status() if app.state.models else {})}

    @app.get('/api/knowledge/recent')
    def recent():
        return manager.list_recent()

    @app.post('/api/knowledge/choose')
    def choose(request: Request):
        return manager.switch(request.headers.get('X-Knowledge-Sequence'), choose=True)

    class SwitchRequest(BaseModel):
        id: str = Field(min_length=1, max_length=64)

    class ModelSwitchRequest(SwitchRequest):
        mode: Literal['knowledge', 'advanced'] = 'knowledge'

    @app.post('/api/knowledge/switch')
    def switch(request: Request, body: SwitchRequest):
        return manager.switch(request.headers.get('X-Knowledge-Sequence'), recent_id=body.id)

    @app.get('/api/models')
    def list_models():
        return {'models':app.state.models.options(), **app.state.models.status()} if app.state.models else {'models':[]}

    @app.post('/api/models/switch')
    def switch_model(request: Request, body: ModelSwitchRequest):
        if not app.state.models:raise HTTPException(409,'当前引擎不支持模型切换')
        if not manager.busy.acquire(blocking=False):raise HTTPException(409,'请等待当前任务完成')
        candidate=None
        def create_candidate():
            nonlocal candidate
            if manager.active:
                candidate=manager.active.app.state.new_session(body.mode)
                return {'session':candidate}
            return {}
        try:
            manager.check_sequence(request.headers.get('X-Knowledge-Sequence'))
            return app.state.models.switch(body.id,request.headers.get('X-Model-Sequence'),locked=True,on_ready=create_candidate)
        except BaseException:
            if candidate:(home/'sessions'/f"{candidate['id']}.json").unlink(missing_ok=True)
            raise
        finally:manager.busy.release()

    class ContextResponse(Response):
        def __init__(self, context, writing):
            super().__init__()
            self.context, self.writing = context, writing

        async def __call__(self, scope, receive, send):
            try:
                await self.context.app(scope, receive, send)
            finally:
                manager.release(self.context, self.writing)

    @app.api_route('/api/{path:path}', methods=['GET', 'POST', 'PATCH', 'DELETE'])
    def knowledge_request(request: Request, path: str):
        writing = request.method != 'GET'
        if writing and app.state.models and not path.endswith('/cancel'):
            app.state.models.check_sequence(request.headers.get('X-Model-Sequence'))
        context = manager.acquire(request.headers.get('X-Knowledge-Sequence'), writing)
        return ContextResponse(context, writing)

    if static_dir and Path(static_dir).exists():
        app.mount('/', StaticFiles(directory=static_dir, html=True), name='frontend')
    return app

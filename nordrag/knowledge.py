"""Process-local knowledge selection, with leases for in-flight responses."""
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException
from .operations import OperationLock
from .package import open_package
from .util import read_json, write_json
from .logging_utils import logger


def choose_file():
    # All Tk operations (including destruction) stay on the picker thread.
    from tkinter import Tk, filedialog
    window = Tk()
    try:
        window.withdraw()
        window.attributes('-topmost', True)
        return filedialog.askopenfilename(parent=window, title='选择 RadioMind 知识库',
                                          filetypes=[('RadioMind 知识库', '*.ragkb')]) or None
    finally:
        window.destroy()


@dataclass(eq=False)
class KnowledgeContext:
    root: Path
    manifest: dict
    app: object
    path: str | None = None
    readers: int = 0
    writers: int = 0
    retired: bool = False
    owned: bool = True


class KnowledgeManager:
    def __init__(self, engines, home, factory, picker=None):
        self.engines, self.home, self.factory = engines, Path(home), factory
        self.home.mkdir(parents=True, exist_ok=True)
        self.busy = OperationLock(self.home)
        self.condition = threading.Condition(threading.RLock())
        self.sequence = 0
        self.active = None
        self.contexts = []
        self.switching = False
        self.closed = False
        self.startup_error = None
        self.picker = picker or choose_file
        self.picker_thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix='knowledge-picker')
        self.settings_path = self.home / 'settings.json'
        try:
            self.settings = read_json(self.settings_path) if self.settings_path.exists() else {}
            if not isinstance(self.settings, dict):
                self.settings = {}
        except (OSError, ValueError):
            self.settings = {}
        recent = self.settings.get('recent_knowledge', [])
        self.recent = [r for r in recent if isinstance(r, dict) and all(isinstance(r.get(k), str) for k in ('id', 'name', 'path'))][:10] if isinstance(recent, list) else []

    def make_context(self, root, manifest, path=None, owned=True):
        context = KnowledgeContext(root, manifest, self.factory(root, manifest, self.busy), path, owned=owned)
        def retain_worker():
            with self.condition:
                context.readers += 1
        context.app.state.retain_worker = retain_worker
        context.app.state.release_worker = lambda: self.release(context)
        return context

    def adopt(self, root, manifest):
        # Caller owns legacy roots; newly opened contexts are managed here.
        self.active = self.make_context(root, manifest, owned=False)
        self.contexts.append(self.active)
        self.sequence = 1

    def status(self):
        with self.condition:
            return {'knowledge': self.active.manifest if self.active else None,
                    'sequence': self.sequence, 'busy': self.busy.locked(),
                    'switching': self.switching, 'startup_error': self.startup_error}

    def list_recent(self):
        with self.condition:
            current = self.active.path if self.active else None
            return [{**r, 'current': r['path'] == current} for r in self.recent]

    def check_sequence(self, sequence):
        if str(self.sequence) != sequence:
            raise HTTPException(409, {'code': 'knowledge_changed', 'message': '知识库已切换，请刷新状态后重试'})

    def acquire(self, sequence, writing=False):
        with self.condition:
            self.check_sequence(sequence)
            if self.switching or self.closed:
                raise HTTPException(409, '正在切换知识库，请稍候')
            context = self.active
            if context is None:
                raise HTTPException(409, '请先选择知识库')
            context.readers += 1
            context.writers += int(writing)
            return context

    def release(self, context, writing=False):
        with self.condition:
            context.readers -= 1
            context.writers -= int(writing)
            self.condition.notify_all()
            self._clean(context)

    def _clean(self, context):
        if context.retired and context.readers == 0:
            if context.owned:
                try:
                    shutil.rmtree(context.root)
                except OSError:
                    # Retain for retry at shutdown/startup; a valid switch stays valid.
                    logger.warning('knowledge_cleanup_deferred')
                    return
            if context in self.contexts:
                self.contexts.remove(context)

    def switch(self, sequence, *, recent_id=None, path=None, choose=False):
        with self.condition:
            self.check_sequence(sequence)
            if self.closed or self.switching or not self.busy.acquire(blocking=False):
                raise HTTPException(409, '请等待当前任务完成或先停止生成，再切换知识库')
            self.switching = True
        candidate = None
        try:
            if choose:
                try:
                    path = self.picker_thread.submit(self.picker).result()
                except Exception as exc:
                    raise HTTPException(400, '无法打开文件选择窗口，请重试') from exc
                if not path:
                    return {'cancelled': True, 'sequence': self.sequence}
            elif recent_id is not None:
                with self.condition:
                    entry = next((r for r in self.recent if r['id'] == recent_id), None)
                if entry is None:
                    raise HTTPException(404, '最近使用的知识库不存在，请重新选择文件')
                path = entry['path']
            if not path:
                raise HTTPException(400, '请选择 .ragkb 知识库文件')
            path = Path(path).resolve()
            if path.suffix.lower() != '.ragkb':
                raise HTTPException(400, '请选择 .ragkb 知识库文件')
            # Drain short mutations before loading persisted labels. Preview reads
            # can continue on the retired context without delaying this switch.
            with self.condition:
                self.condition.wait_for(lambda: not self.active or self.active.writers == 0)
            root, manifest = open_package(path, self.home / 'work', self.engines.embedding_id)
            try:
                candidate = self.make_context(root, manifest, str(path))
            except BaseException:
                shutil.rmtree(root)
                raise
            with self.condition:
                if self.closed:
                    raise HTTPException(409, '程序正在退出')
                key = os.path.normcase(str(path))
                previous = next((r for r in self.recent if os.path.normcase(r['path']) == key), None)
                item = {'id': previous['id'] if previous else uuid.uuid4().hex,
                        'name': manifest['name'], 'path': str(path), 'opened_at': time.time()}
                recent = [item] + [r for r in self.recent if os.path.normcase(r['path']) != key]
                settings = {**self.settings, 'knowledge': str(path), 'recent_knowledge': recent[:10]}
                # Persist before commit: a settings error leaves the old context usable.
                write_json(self.settings_path, settings)
                old = self.active
                self.active = candidate
                self.contexts.append(candidate)
                candidate = None
                self.sequence += 1
                self.settings, self.recent = settings, recent[:10]
                self.startup_error = None
                if old:
                    old.retired = True
                    self._clean(old)
                return {'cancelled': False, 'sequence': self.sequence}
        except FileNotFoundError as exc:
            raise HTTPException(400, '知识库文件不存在或已移动，请重新选择') from exc
        except PermissionError as exc:
            raise HTTPException(400, '无法读取知识库或保存设置，请检查文件访问权限') from exc
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(400, f'知识库加载失败：{exc}') from exc
        finally:
            if candidate:
                candidate.retired = True
                self._clean(candidate)
            with self.condition:
                self.switching = False
                self.busy.release()
                self.condition.notify_all()

    def restore(self, path=None, choose=False):
        if choose:
            return
        path = path or self.settings.get('knowledge')
        if path:
            try:
                self.switch(str(self.sequence), path=path)
            except HTTPException as exc:
                self.startup_error = str(exc.detail)

    def close(self):
        with self.condition:
            self.closed = True
            for context in list(self.contexts):
                for event in list(context.app.state.jobs.values()):
                    event.set()
                context.retired = True
                self._clean(context)
        self.picker_thread.shutdown(wait=False, cancel_futures=True)

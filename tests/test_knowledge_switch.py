import threading
import concurrent.futures
import shutil
import pytest
from fastapi.testclient import TestClient
from nordrag.api import create_app
from nordrag.builder import build
from test_api import ChatEngines


TOKEN = {"X-Nord-Token": "selection-test"}


def headers(client):
    status = client.get('/api/status', headers=TOKEN).json()
    return TOKEN | {'X-Knowledge-Sequence': str(status['sequence'])}


def test_first_selection_cancel_failure_and_stale_tab(deck, tmp_path):
    engine = ChatEngines()
    package = tmp_path / 'first.ragkb'
    build(deck.parent, '第一库', package, tmp_path / 'cache', engine, threading.Event())
    choices = iter([None, str(package), str(tmp_path / 'missing.ragkb')])
    app = create_app(None, None, engine, tmp_path / 'home', token='selection-test', picker=lambda: next(choices))
    with TestClient(app) as client:
        assert client.get('/api/status', headers=TOKEN).json()['knowledge'] is None
        old = headers(client)
        assert client.post('/api/sessions', headers=old).status_code == 409
        assert client.post('/api/knowledge/choose', headers=old).json()['cancelled']
        assert client.post('/api/knowledge/choose', headers=old).status_code == 200
        current = headers(client)
        assert client.get('/api/status', headers=TOKEN).json()['knowledge']['name'] == '第一库'
        assert client.get('/api/documents', headers=old).json()['code'] == 'knowledge_changed'
        assert client.post('/api/sessions', headers=TOKEN).status_code == 409
        assert client.post('/api/knowledge/choose', headers=current).status_code == 400
        assert headers(client) == current
        assert client.get('/api/documents', headers=current).json()
        assert len(client.get('/api/knowledge/recent', headers=TOKEN).json()) == 1


def test_switch_preserves_sessions_labels_and_history(deck, tmp_path):
    engine = ChatEngines()
    packages = []
    for index in range(2):
        package = tmp_path / f'{index}.ragkb'
        build(deck.parent, f'知识库{index}', package, tmp_path / 'cache', engine, threading.Event())
        packages.append(str(package))
    choices = iter(packages)
    app = create_app(None, None, engine, tmp_path / 'home', token='selection-test', picker=lambda: next(choices))
    with TestClient(app) as client:
        client.post('/api/knowledge/choose', headers=headers(client)).raise_for_status()
        h = headers(client)
        sid = client.post('/api/sessions', headers=h).json()['id']
        doc = client.get('/api/documents', headers=h).json()[0]
        client.patch('/api/documents/' + doc['id'], headers=h, json={'category': '已保存', 'tags': ['标签']}).raise_for_status()
        client.post('/api/knowledge/choose', headers=h).raise_for_status()
        assert client.get('/api/sessions', headers=headers(client)).json() == []
        assert client.get('/api/sessions/' + sid, headers=headers(client)).status_code == 409
        recent = client.get('/api/knowledge/recent', headers=TOKEN).json()
        assert [x['name'] for x in recent] == ['知识库1', '知识库0']
        client.post('/api/knowledge/switch', headers=headers(client), json={'id': recent[1]['id']}).raise_for_status()
        assert client.get('/api/sessions', headers=headers(client)).json()[0]['id'] == sid
        assert client.get('/api/documents', headers=headers(client)).json()[0]['category'] == '已保存'
        assert len(client.get('/api/knowledge/recent', headers=TOKEN).json()) == 2


@pytest.fixture
def packages(deck, tmp_path):
    engine = ChatEngines()
    result = []
    for index in range(2):
        path = tmp_path / f'library-{index}.ragkb'
        build(deck.parent, f'库{index}', path, tmp_path / 'cache', engine, threading.Event())
        result.append(path)
    return engine, result


def test_busy_concurrent_picker_and_auth(packages, tmp_path):
    engine, files = packages
    entered, done = threading.Event(), threading.Event()
    def picker():
        entered.set()
        assert done.wait(4)
        return str(files[0])
    app = create_app(None, None, engine, tmp_path / 'home', token='selection-test', picker=picker)
    with TestClient(app) as client:
        h = headers(client)
        assert client.post('/api/knowledge/choose').status_code == 403
        assert client.post('/api/knowledge/choose', headers=h | {'Origin': 'https://evil.example'}).status_code == 403
        assert not entered.is_set()
        assert app.state.knowledge.busy.acquire()
        try:
            assert client.post('/api/knowledge/choose', headers=h).status_code == 409
        finally:
            app.state.knowledge.busy.release()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            request = pool.submit(client.post, '/api/knowledge/choose', headers=h)
            try:
                assert entered.wait(2)
                assert client.post('/api/knowledge/choose', headers=h).status_code == 409
                assert client.get('/api/status', headers=TOKEN).json()['switching']
            finally:
                done.set()
            assert request.result(timeout=4).status_code == 200


def test_lease_keeps_preview_files_until_response_finishes(packages, tmp_path):
    engine, files = packages
    app = create_app(None, None, engine, tmp_path / 'home', token='selection-test')
    manager = app.state.knowledge
    manager.restore(files[0])
    context = manager.acquire(str(manager.sequence))
    old_root = context.root
    manager.switch(str(manager.sequence), path=files[1])
    assert old_root.exists()
    assert (old_root / 'documents.json').is_file()
    manager.release(context)
    assert not old_root.exists()
    new_root = manager.active.root
    manager.close()
    assert not new_root.exists()


def test_recent_limit_restore_legacy_and_moved_file(packages, tmp_path):
    from nordrag.util import write_json
    engine, files = packages
    home = tmp_path / 'home'
    write_json(home / 'settings.json', {'knowledge': str(files[0]), 'unrelated': True})
    app = create_app(None, None, engine, home, token='selection-test')
    manager = app.state.knowledge
    manager.restore()
    assert manager.active.manifest['name'] == '库0'
    for index in range(11):
        path = tmp_path / f'copy-{index}.ragkb'
        shutil.copyfile(files[0], path)
        manager.switch(str(manager.sequence), path=path)
    assert len(manager.list_recent()) == 10
    recent = manager.list_recent()
    assert recent[0]['path'].endswith('copy-10.ragkb')
    assert manager.settings['unrelated']
    current_path = manager.active.path
    manager.close()
    app2 = create_app(None, None, engine, home, token='selection-test')
    app2.state.knowledge.restore()
    assert app2.state.knowledge.active.path == current_path
    app2.state.knowledge.close()
    from pathlib import Path
    Path(current_path).unlink()
    app3 = create_app(None, None, engine, home, token='selection-test')
    app3.state.knowledge.restore()
    with TestClient(app3) as client:
        state = client.get('/api/status', headers=TOKEN).json()
        assert state['knowledge'] is None and state['startup_error']
        assert client.post('/api/knowledge/switch', headers=headers(client), json={'id': recent[0]['id']}).status_code == 400


@pytest.mark.parametrize('failure', ['corrupt', 'embedding', 'permission', 'settings'])
def test_failed_load_retains_context(packages, tmp_path, monkeypatch, failure):
    import nordrag.knowledge as module
    engine, files = packages
    manager = create_app(None, None, engine, tmp_path / 'home').state.knowledge
    manager.restore(files[0])
    original = manager.active
    seq = manager.sequence
    if failure == 'corrupt':
        files[1].write_bytes(b'not a zip')
    elif failure == 'embedding':
        engine.embedding_id = 'different-embedding'
    elif failure == 'permission':
        monkeypatch.setattr(module, 'open_package', lambda *a: (_ for _ in ()).throw(PermissionError()))
    else:
        monkeypatch.setattr(module, 'write_json', lambda *a: (_ for _ in ()).throw(PermissionError()))
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        manager.switch(str(seq), path=files[1])
    assert manager.active is original and manager.sequence == seq
    assert original.root.exists() and not manager.busy.locked()
    assert len(list((tmp_path / 'home' / 'work').iterdir())) == 1
    manager.close()


def test_generation_and_export_block_switch(packages, tmp_path):
    engine, files = packages
    entered, resume = threading.Event(), threading.Event()
    def stream(*args, **kwargs):
        entered.set()
        assert resume.wait(4)
        yield '保修为24个月 [1]'
    engine.stream = stream
    app = create_app(None, None, engine, tmp_path / 'home', token='selection-test', picker=lambda: str(files[1]))
    manager = app.state.knowledge
    manager.restore(files[0])
    with TestClient(app) as client:
        h = headers(client)
        sid = client.post('/api/sessions', headers=h).json()['id']
        with concurrent.futures.ThreadPoolExecutor() as pool:
            response = pool.submit(client.post, '/api/chat', headers=h, json={'session_id': sid, 'question': '保修多久？'})
            try:
                assert entered.wait(2)
                assert client.post('/api/knowledge/choose', headers=h).status_code == 409
            finally:
                resume.set()
            assert '"type": "done"' in response.result(timeout=4).text
        endpoint = next(r.endpoint for r in manager.active.app.routes if r.path == '/api/export')
        exported = endpoint()
        try:
            assert client.post('/api/knowledge/choose', headers=h).status_code == 409
        finally:
            import asyncio
            async def send(message): pass
            async def receive(): return {'type': 'http.request', 'body': b''}
            asyncio.run(exported({'type': 'http', 'method': 'POST', 'headers': [], 'extensions': {}}, receive, send))
        assert client.post('/api/knowledge/choose', headers=h).status_code == 200


def test_native_picker_runs_all_tk_operations_on_its_thread(monkeypatch):
    import tkinter
    from tkinter import filedialog
    from nordrag.knowledge import choose_file
    calls = []
    class Window:
        def __init__(self): calls.append(('create', threading.get_ident()))
        def withdraw(self): calls.append(('withdraw', threading.get_ident()))
        def attributes(self, *args): calls.append(('attributes', threading.get_ident()))
        def destroy(self): calls.append(('destroy', threading.get_ident()))
    def dialog(**kwargs):
        calls.append(('dialog', threading.get_ident()))
        assert kwargs['filetypes'][0][1] == '*.ragkb'
        return ''
    monkeypatch.setattr(tkinter, 'Tk', Window)
    monkeypatch.setattr(filedialog, 'askopenfilename', dialog)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(choose_file).result() is None
    assert len({thread for _, thread in calls}) == 1
    assert calls[-1][0] == 'destroy'
    assert calls[0][1] != threading.get_ident()


@pytest.mark.parametrize('mode', ['empty', 'missing', 'explicit', 'choose'])
def test_launcher_opens_ui_without_forcing_dialog(packages, tmp_path, monkeypatch, mode):
    from nordrag import launcher
    from nordrag.util import write_json
    engine, files = packages
    home = tmp_path / 'launch-home'
    (tmp_path / 'frontend' / 'dist').mkdir(parents=True)
    if mode in ('choose', 'missing'):
        write_json(home / 'settings.json', {'knowledge': str(files[0] if mode == 'choose' else tmp_path / 'gone.ragkb')})
    monkeypatch.setattr(launcher, 'data_home', lambda: home)
    monkeypatch.setattr(launcher, 'app_root', lambda: tmp_path)
    monkeypatch.setattr(launcher, 'load_config', lambda path: {})
    monkeypatch.setattr(launcher, 'configure_logging', lambda *args: None)
    monkeypatch.setattr(launcher, 'Engines', lambda config: engine)
    monkeypatch.setattr(engine, 'close', lambda: None, raising=False)
    snapshots = []
    monkeypatch.setattr(launcher.uvicorn, 'run', lambda app, **kwargs: snapshots.append(app.state.knowledge.status()))
    args = ['--no-browser']
    if mode == 'explicit': args += ['--knowledge', str(files[0])]
    if mode == 'choose': args += ['--choose']
    assert launcher.main(args) == 0
    assert bool(snapshots[0]['knowledge']) == (mode == 'explicit')
    assert bool(snapshots[0]['startup_error']) == (mode == 'missing')


def test_shutdown_keeps_worker_files_until_cancelled(packages, tmp_path):
    engine, files = packages
    entered, stopped = threading.Event(), threading.Event()
    def embed(*args, **kwargs):
        entered.set()
        assert stopped.wait(4)
        return [[1., 0., 0.]]
    engine.embed = embed
    engine.cancel = stopped.set
    app = create_app(None, None, engine, tmp_path / 'home', token='selection-test')
    manager = app.state.knowledge
    manager.restore(files[0])
    root = manager.active.root
    with TestClient(app) as client:
        h = headers(client)
        sid = client.post('/api/sessions', headers=h).json()['id']
        with concurrent.futures.ThreadPoolExecutor() as pool:
            response = pool.submit(client.post, '/api/chat', headers=h, json={'session_id':sid, 'question':'保修多久？'})
            assert entered.wait(2)
            manager.close()
            assert '"type": "cancelled"' in response.result(timeout=4).text
        assert stopped.is_set()
        assert not root.exists()

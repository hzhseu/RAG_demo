"""UI test harness ONLY: explicit synthetic model, never shipped in the runtime."""
import sys
import threading
import argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from test_api import ChatEngines
from nordrag.builder import build
from nordrag.api import create_app
import uvicorn

parser = argparse.ArgumentParser()
parser.add_argument('--selection-smoke', action='store_true', help='Use scripted file selections ONLY in this test harness')
parser.add_argument('--advanced-smoke', action='store_true', help='Use two synthetic models ONLY for mode-switch UI tests')
parser.add_argument('--port', type=int, default=8765)
args = parser.parse_args()
folder=ROOT/'artifacts/ui-test';folder.mkdir(parents=True,exist_ok=True)
out=folder/'fixture.ragkb';engine=ChatEngines()
if args.advanced_smoke:
    from nordrag.chat_models import identity
    class ModeTestEngine(ChatEngines):
        cfg = {'chat_model': __file__, 'llama_server': __file__, 'chat_model_sha256': 'a'*64}
        @property
        def model_identity(self): return identity(self.cfg)
        def select_model(self, cfg): self.cfg = cfg
    engine = ModeTestEngine()
if not out.exists():
    build(ROOT/'artifacts/fixtures/pptx','北境 · 产品与运营知识库',out,folder/'cache',engine,threading.Event())
picker = None
if args.selection_smoke or args.advanced_smoke:
    second = folder/'second.ragkb'
    if not second.exists():
        build(ROOT/'artifacts/fixtures/pptx','RadioMind · 流程知识库',second,folder/'cache',engine,threading.Event())
    if args.advanced_smoke:
        from itertools import cycle
        selections = cycle([str(second), str(out)])
    else:
        selections = iter([None, str(out), str(folder/'missing.ragkb'), str(second)])
    picker = lambda: next(selections, None)
home=folder/('advanced-data' if args.advanced_smoke else 'selection-data' if args.selection_smoke else 'data')
app=create_app(None,None,engine,home,token='ui-test-only',static_dir=ROOT/'frontend/dist',picker=picker)
if not args.selection_smoke:
    app.state.knowledge.restore(out)
if args.advanced_smoke:
    from nordrag.model_manager import ModelManager
    models = ModelManager(engine, home, app.state.knowledge.busy, models={
        'default': {'name': 'Test Model One', 'cfg': engine.cfg},
        'second': {'name': 'Test Model Two', 'cfg': engine.cfg | {'model_id': 'second'}},
    }, validator=lambda cfg: None)
    app.state.models = models
    factory = app.state.knowledge.factory
    def with_models(*args):
        scoped = factory(*args)
        scoped.state.models = models
        return scoped
    app.state.knowledge.factory = with_models
    if app.state.knowledge.active:
        app.state.knowledge.active.app.state.models = models
uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False)

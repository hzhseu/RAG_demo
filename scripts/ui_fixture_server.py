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
args = parser.parse_args()
folder=ROOT/'artifacts/ui-test';folder.mkdir(parents=True,exist_ok=True)
out=folder/'fixture.ragkb';engine=ChatEngines()
if not out.exists():
    build(ROOT/'artifacts/fixtures/pptx','北境 · 产品与运营知识库',out,folder/'cache',engine,threading.Event())
picker = None
if args.selection_smoke:
    second = folder/'second.ragkb'
    if not second.exists():
        build(ROOT/'artifacts/fixtures/pptx','RadioMind · 流程知识库',second,folder/'cache',engine,threading.Event())
    selections = iter([None, str(out), str(folder/'missing.ragkb'), str(second)])
    picker = lambda: next(selections, None)
app=create_app(None,None,engine,folder/('selection-data' if args.selection_smoke else 'data'),token='ui-test-only',static_dir=ROOT/'frontend/dist',picker=picker)
if not args.selection_smoke:
    app.state.knowledge.restore(out)
uvicorn.run(app,host='127.0.0.1',port=8765,access_log=False)

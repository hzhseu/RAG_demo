"""UI test harness ONLY: explicit synthetic model, never shipped in the runtime."""
import sys
import threading
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from test_api import ChatEngines
from nordrag.builder import build
from nordrag.package import open_package
from nordrag.api import create_app
import uvicorn

folder=ROOT/'artifacts/ui-test';folder.mkdir(parents=True,exist_ok=True)
out=folder/'fixture.ragkb';engine=ChatEngines()
if not out.exists():
    build(ROOT/'artifacts/fixtures/pptx','北境 · 产品与运营知识库',out,folder/'cache',engine,threading.Event())
root,manifest=open_package(out,folder/'work',engine.embedding_id)
app=create_app(root,manifest,engine,folder/'data',token='ui-test-only',static_dir=ROOT/'frontend/dist')
uvicorn.run(app,host='127.0.0.1',port=8765,access_log=False)

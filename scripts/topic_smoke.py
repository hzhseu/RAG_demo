import json
import sys
import threading
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from nordrag.config import load_config
from nordrag.engines import Engines
from nordrag.package import open_package
from nordrag.index import all_chunks
from nordrag.generation import summarize_topic
from nordrag.util import read_json,write_json

e=Engines(load_config());started=time.perf_counter()
try:
    root,m=open_package(ROOT/'artifacts/real-test.ragkb',ROOT/'artifacts/topic-test',e.embedding_id)
    names={d['id']:d['name'] for d in read_json(root/'documents.json')}
    chunks=[c|{'doc_name':names[c['doc_id']]} for c in all_chunks(root)]
    result=summarize_topic(e,chunks,threading.Event(),lambda x:print(json.dumps(x),flush=True))
    write_json(ROOT/'artifacts/topic-report.json',result|{'elapsed_seconds':time.perf_counter()-started})
    print('Real topic synthesis completed',flush=True)
finally:e.close()

"""Run the portable EXE with developer PATH removed and capture its local URL."""
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8',errors='replace')
sys.path.insert(0,str(ROOT))
from nordrag.util import write_json

env=os.environ.copy()
env['PATH']=str(Path(os.environ['WINDIR'])/'System32')
env['PYTHONPATH']='';env['PYTHONHOME']=''
env['NORDRAG_DATA']=str(ROOT/'artifacts/packaged-data')
(ROOT/'artifacts/stop-packaged').unlink(missing_ok=True)
process=subprocess.Popen([str(ROOT/'dist/NordRAG/nord-chat.exe'),'--knowledge',str(ROOT/'dist/NordRAG/samples/demo.ragkb'),'--no-browser'],cwd=ROOT/'dist/NordRAG',env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='mbcs',errors='replace',creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
url=None
try:
    for line in process.stdout:
        print(line.strip(),flush=True)
        match=re.search(r'http://127\.0\.0\.1:\d+/#token=[\w-]+',line)
        if match:url=match[0];break
        if process.poll() is not None:break
    if not url:raise RuntimeError('Packaged launcher failed')
    base,token=url.split('/#token=')
    for _ in range(50):
        try:
            response=httpx.get(base+'/api/status',headers={'X-Nord-Token':token},timeout=2,trust_env=False)
            response.raise_for_status();break
        except httpx.HTTPError:time.sleep(.2)
    data=response.json()
    write_json(ROOT/'artifacts/packaged-url.json',{'url':url,'pid':process.pid})
    write_json(ROOT/'artifacts/packaged-report.json',{'launch_with_clean_path':True,'status':data,'clean_windows':False})
    # Parent task uses this window to run browser checks, then terminate via stop file.
    while not (ROOT/'artifacts/stop-packaged').exists():
        if process.poll() is not None:raise RuntimeError('Packaged app exited unexpectedly')
        time.sleep(.5)
finally:
    if process.poll() is None:
        import signal
        process.send_signal(signal.CTRL_BREAK_EVENT)
        try:process.wait(timeout=15)
        except subprocess.TimeoutExpired:process.kill();process.wait()

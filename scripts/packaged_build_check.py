"""End-to-end PPTX ingestion through the EXE with no developer PATH."""
import os
import argparse
import subprocess
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from nordrag.util import write_json
parser=argparse.ArgumentParser()
parser.add_argument('--output',type=Path,default=ROOT/'artifacts/packaged-built.ragkb')
parser.add_argument('--input',type=Path,default=ROOT/'dist/NordRAG/samples/pptx')
parser.add_argument('--data-dir',type=Path,default=ROOT/'artifacts/packaged-build-data')
args=parser.parse_args()
env=os.environ.copy();env['PATH']=str(Path(os.environ['WINDIR'])/'System32');env['PYTHONHOME']='';env['PYTHONPATH']='';env['NORDRAG_DATA']=str(args.data_dir.resolve())
output=args.output.resolve()
if output.exists():raise SystemExit('Existing output preserved; choose a fresh test output')
started=time.perf_counter()
with (ROOT/'artifacts/packaged-build.log').open('wb') as log:
    result=subprocess.run([str(ROOT/'dist/NordRAG/kb-builder.exe'),'build','--input',str(args.input.resolve()),'--name','Portable ingestion validation','--output',str(output),'--yes'],cwd=ROOT/'dist/NordRAG',env=env,stdout=log,stderr=subprocess.STDOUT,timeout=900)
report={'exit_code':result.returncode,'knowledge_created':output.exists(),'output':str(output),'seconds':round(time.perf_counter()-started,2),'developer_path_removed':True,'clean_windows':False}
write_json(ROOT/'artifacts/packaged-build-report.json',report)
print(report,flush=True)
raise SystemExit(result.returncode)

"""Build a self-contained Windows folder. Refuses to label missing assets as a release."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from nordrag.config import load_config, preflight
from nordrag.util import digest, write_json


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--app-only',action='store_true',help='Developer build only; deliberately not a complete offline release')
    args=parser.parse_args()
    if not (ROOT/'frontend/dist/index.html').exists():
        raise SystemExit('Build frontend first')
    if not args.app_only:
        errors=preflight(load_config(),build=True)
        if errors:raise SystemExit('\n'.join(errors))
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--name','NordRAG','--paths',str(ROOT),'--collect-all','uvicorn','--collect-all','pptx','--hidden-import','tkinter','--add-data',f'{ROOT / "nordrag/ocr_worker.py"};nordrag',str(ROOT/'scripts/entry.py')],cwd=ROOT,check=True)
    target=ROOT/'dist/NordRAG'
    (target/'NordRAG.exe').rename(target/'nord-chat.exe')
    shutil.copy2(target/'nord-chat.exe',target/'kb-builder.exe')
    shutil.copytree(ROOT/'frontend/dist',target/'frontend/dist',dirs_exist_ok=True)
    shutil.copy2(ROOT/'README.md',target/'README.md')
    shutil.copytree(ROOT/'docs',target/'docs',dirs_exist_ok=True)
    sample = ROOT/'artifacts/delivery-demo.ragkb'
    if not sample.exists(): sample = ROOT/'artifacts/final-demo.ragkb'
    if not sample.exists(): sample = ROOT/'artifacts/real-test.ragkb'
    if sample.exists():
        (target/'samples').mkdir(exist_ok=True)
        shutil.copy2(sample,target/'samples/demo.ragkb')
        shutil.copytree(ROOT/'artifacts/fixtures/pptx',target/'samples/pptx',dirs_exist_ok=True)
        (target/'Try-demo.cmd').write_text('@echo off\r\n"%~dp0nord-chat.exe" --knowledge "%~dp0samples\\demo.ragkb"\r\n',encoding='ascii')
    if not args.app_only:
        shutil.copytree(ROOT/'runtime',target/'runtime',ignore=shutil.ignore_patterns('downloads','__pycache__'),dirs_exist_ok=True)
        if (ROOT/'runtime/crt').is_dir():
            for dll in (ROOT/'runtime/crt').glob('*.dll'):
                shutil.copy2(dll,target/'_internal'/dll.name)
        shutil.copy2(ROOT/'runtime.json',target/'runtime.json')
    else:
        (target/'APP-ONLY-NOT-OFFLINE-RELEASE.txt').write_text('Development build: runtime assets not included.',encoding='utf-8')
    write_json(target/'checksums.json',{p.relative_to(target).as_posix():digest(p) for p in target.rglob('*') if p.is_file() and p.name!='checksums.json'})
    print(f'Built: {target}')


if __name__=='__main__':main()

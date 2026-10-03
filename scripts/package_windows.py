"""Build a self-contained Windows folder. Refuses to label missing assets as a release."""
import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from uuid import uuid4
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from nordrag.chat_models import load_models, unavailable_reason
from nordrag.config import load_config, preflight
from nordrag.util import digest, write_json


def preserve_previous_release(target):
    if not target.exists():
        return None
    dist = ROOT.resolve() / 'dist'
    backup = dist / 'previous-releases' / f'NordRAG-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}'
    # Validate resolved paths before moving a directory on Windows.
    if target.resolve() != dist / 'NordRAG' or not backup.resolve().is_relative_to(dist):
        raise RuntimeError('Refusing to move a release outside the project dist directory')
    backup.parent.mkdir(parents=True, exist_ok=True)
    target.rename(backup)
    print(f'Previous release preserved: {backup}', flush=True)
    return backup


def restore_knowledge_files(previous, target):
    if previous is None:
        return
    for source in previous.rglob('*.ragkb'):
        destination = target / source.relative_to(previous)
        if destination.exists() and digest(destination) != digest(source):
            destination = target / 'preserved-knowledge' / source.relative_to(previous)
        if destination.exists() and digest(destination) != digest(source):
            raise RuntimeError(f'Knowledge file collision; original remains in {previous}')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        report = source.with_suffix('.report.json')
        if report.exists():
            shutil.copy2(report, destination.with_suffix('.report.json'))


def restore_model_catalogs(previous, target):
    if not previous:return
    for name in ('chat-models.json','model-test-models.json'):
        source=previous/name
        if not source.is_file():continue
        catalog=json.loads(source.read_text(encoding='utf-8-sig'))
        for entry in catalog.get('models',[]):
            # Hash IDs for safe directory names; never trust a catalog path as a
            # destination. Existing custom assets remain in the backup as well.
            import hashlib
            key=hashlib.sha256(entry['id'].encode()).hexdigest()[:16]
            for field in ('path','llama_server'):
                raw=entry.get(field)
                if not raw:continue
                original=Path(raw)
                if original.is_absolute() and original.is_relative_to(target):
                    original=previous/original.relative_to(target)
                elif not original.is_absolute():original=previous/original
                if not original.is_file():continue  # Preserve an already unavailable entry.
                candidate=target/Path(raw) if not Path(raw).is_absolute() else None
                if candidate and candidate.is_file() and digest(candidate)==digest(original):
                    continue
                destination=target/'preserved-model-assets'/key/field/original.name
                destination.parent.mkdir(parents=True,exist_ok=True)
                if field=='llama_server':
                    # Keep engine plugins/DLLs together, without altering built-ins.
                    shutil.copytree(original.parent,destination.parent,dirs_exist_ok=True)
                else:shutil.copy2(original,destination)
                entry[field]=destination.relative_to(target).as_posix()
        if name=='chat-models.json' and (target/name).exists():
            shipped=json.loads((target/name).read_text(encoding='utf-8'))
            merged={m['id']:m for m in shipped['models']}
            merged.update({m['id']:m for m in catalog['models']})
            catalog={**shipped,**catalog,'models':list(merged.values())}
        write_json(target/name,catalog)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--app-only',action='store_true',help='Developer build only; deliberately not a complete offline release')
    args=parser.parse_args()
    if not (ROOT/'frontend/dist/index.html').exists():
        raise SystemExit('Build frontend first')
    if not args.app_only:
        errors=preflight(load_config(),build=True)
        errors += [reason for entry in load_models(load_config()).values() if (reason:=unavailable_reason(entry['cfg']))]
        if errors:raise SystemExit('\n'.join(errors))
    previous = preserve_previous_release(ROOT/'dist/NordRAG')
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--name','NordRAG','--paths',str(ROOT),'--collect-all','uvicorn','--collect-all','pptx','--hidden-import','tkinter','--add-data',f'{ROOT / "nordrag/ocr_worker.py"};nordrag',str(ROOT/'scripts/entry.py')],cwd=ROOT,check=True)
    target=ROOT/'dist/NordRAG'
    (target/'NordRAG.exe').rename(target/'nord-chat.exe')
    shutil.copy2(target/'nord-chat.exe',target/'kb-builder.exe')
    shutil.copytree(ROOT/'frontend/dist',target/'frontend/dist',dirs_exist_ok=True)
    shutil.copy2(ROOT/'README.md',target/'README.md')
    shutil.copy2(ROOT/'chat-models.json',target/'chat-models.json')
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
    restore_knowledge_files(previous, target)
    restore_model_catalogs(previous,target)
    write_json(target/'checksums.json',{p.relative_to(target).as_posix():digest(p) for p in target.rglob('*') if p.is_file() and p.name!='checksums.json'})
    print(f'Built: {target}')


if __name__=='__main__':main()

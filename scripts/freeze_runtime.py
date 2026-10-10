import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from nordrag.chat_models import load_models, unavailable_reason
from nordrag.util import digest, write_json, read_json


def main():
    cfg=read_json(ROOT/'runtime.example.json')
    runtime=ROOT/'runtime'
    servers=list((runtime/'llama').rglob('llama-server.exe'))
    soffices=list((runtime/'LibreOffice-25.8.2.2').rglob('soffice.exe'))
    if servers:cfg['llama_server']=servers[0].relative_to(ROOT).as_posix()
    if soffices:cfg['soffice']=soffices[0].relative_to(ROOT).as_posix()
    for key in ('ocr_detection','ocr_recognition'):
        original=ROOT/cfg[key]
        if not original.exists() and original.with_name(original.name+'_infer').exists():cfg[key]=original.with_name(original.name+'_infer').relative_to(ROOT).as_posix()
    for key in ('chat_model','embedding_model','reranker_model'):
        cfg[key+'_sha256']=digest(ROOT/cfg[key])
    for entry in load_models(cfg | {'root':str(ROOT)}).values():
        reason=unavailable_reason(entry['cfg'])
        if reason:raise RuntimeError(reason)
    # Pin parser runtime assets, including OCR and LibreOffice, into cache identity.
    files={p.relative_to(runtime).as_posix():digest(p) for p in runtime.rglob('*') if p.is_file() and 'downloads' not in p.parts and '__pycache__' not in p.parts and p.name!='runtime-lock.json'}
    write_json(runtime/'runtime-lock.json',files)
    cfg['runtime_digest']=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
    write_json(ROOT/'runtime.json',cfg)
    print('Pinned runtime.json and runtime/runtime-lock.json')


if __name__=='__main__':main()

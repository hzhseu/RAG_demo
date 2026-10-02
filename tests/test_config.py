from nordrag.config import preflight
from nordrag.util import write_json, digest
import hashlib
import json


def test_runtime_lock_detects_modified_non_model_asset(tmp_path):
    runtime=tmp_path/'runtime'; runtime.mkdir()
    for n in ('chat.gguf','embedding.gguf','llama.exe','dependency.dll'):
        (runtime/n).write_bytes(b'original')
    files={p.name:digest(p) for p in runtime.iterdir()}
    write_json(runtime/'runtime-lock.json',files)
    cfg={'root':str(tmp_path),'llama_server':'runtime/llama.exe','chat_model':'runtime/chat.gguf','embedding_model':'runtime/embedding.gguf','chat_model_sha256':digest(runtime/'chat.gguf'),'embedding_model_sha256':digest(runtime/'embedding.gguf'),'runtime_digest':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()}
    assert not preflight(cfg)
    (runtime/'dependency.dll').write_bytes(b'tampered')
    assert preflight(cfg)

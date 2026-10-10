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


def test_optional_answer_damage_does_not_block_embedding(tmp_path):
    runtime=tmp_path/'runtime';(runtime/'models').mkdir(parents=True)
    for name in ('models/old.gguf','models/new.gguf','models/embed.gguf','llama.exe'):(runtime/name).write_bytes(b'original')
    files={p.relative_to(runtime).as_posix():digest(p) for p in runtime.rglob('*') if p.is_file()}
    write_json(runtime/'runtime-lock.json',files)
    cfg={'root':str(tmp_path),'llama_server':'runtime/llama.exe','chat_model':'runtime/models/old.gguf','embedding_model':'runtime/models/embed.gguf','chat_model_sha256':digest(runtime/'models/old.gguf'),'embedding_model_sha256':digest(runtime/'models/embed.gguf'),'runtime_digest':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()}
    (runtime/'models/old.gguf').write_bytes(b'bad')
    (runtime/'models/new.gguf').unlink()
    assert preflight(cfg,check_chat=False)==[]
    assert preflight(cfg)
    (runtime/'models/embed.gguf').write_bytes(b'bad')
    assert preflight(cfg,check_chat=False)


def test_optional_reranker_damage_does_not_block_chat_or_build(tmp_path):
    runtime=tmp_path/'runtime'; (runtime/'models').mkdir(parents=True)
    for name in ('models/chat.gguf','models/embed.gguf','models/rank.gguf','llama.exe'):
        (runtime/name).write_bytes(b'original')
    files={p.relative_to(runtime).as_posix():digest(p) for p in runtime.rglob('*') if p.is_file()}
    write_json(runtime/'runtime-lock.json',files)
    cfg=dict(root=str(tmp_path), llama_server='runtime/llama.exe', chat_model='runtime/models/chat.gguf',
             embedding_model='runtime/models/embed.gguf', reranker_model='runtime/models/rank.gguf',
             chat_model_sha256=digest(runtime/'models/chat.gguf'), embedding_model_sha256=digest(runtime/'models/embed.gguf'),
             runtime_digest=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest())
    (runtime/'models/rank.gguf').unlink()
    assert preflight(cfg) == []

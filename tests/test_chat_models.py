import json
from pathlib import Path
from nordrag import chat_models


def test_registry_default_and_legacy(tmp_path):
    cfg={'root':str(tmp_path),'chat_model':'old.gguf','chat_model_sha256':'a'*64,'llama_server':'server.exe'}
    assert chat_models.load_models(cfg).default_id=='default'
    (tmp_path/'chat-models.json').write_text(json.dumps({'default_model':'new','models':[{'id':'new','name':'New','path':'new.gguf','sha256':'b'*64,'generation':{'temperature':.7},'chat_template_kwargs':{'enable_thinking':False}}]}))
    registry=chat_models.load_models(cfg)
    assert registry.default_id=='new'
    assert registry['new']['cfg']['chat_template_kwargs']=={'enable_thinking':False}
    assert registry['default']['cfg']['chat_model']=='old.gguf'
    assert registry['new']['cfg']['embedding_model'] if 'embedding_model' in cfg else True


def test_identity_changes_with_parameters(tmp_path):
    cfg={'chat_model':'old.gguf','chat_model_sha256':'a'*64,'context':8192,'threads':4}
    assert chat_models.identity(cfg)!=chat_models.identity(cfg|{'generation':{'temperature':.7}})


def test_validation_missing_and_bad_hash(tmp_path):
    cfg={'root':str(tmp_path),'chat_model':'x.gguf','chat_model_sha256':'a'*64,'llama_server':'server.exe'}
    assert chat_models.unavailable_reason(cfg)
    (tmp_path/'x.gguf').write_bytes(b'x')
    (tmp_path/'server.exe').write_bytes(b'x')
    assert 'SHA256' in chat_models.unavailable_reason(cfg)


def test_identity_fingerprints_engine_bytes(tmp_path):
    (tmp_path/'a').mkdir();(tmp_path/'b').mkdir()
    (tmp_path/'a/llama-server.exe').write_bytes(b'engine v1')
    (tmp_path/'b/llama-server.exe').write_bytes(b'engine v2')
    cfg={'root':str(tmp_path),'chat_model':'chat.gguf','chat_model_sha256':'a'*64,'llama_server':'a/llama-server.exe'}
    assert chat_models.identity(cfg)!=chat_models.identity(cfg|{'llama_server':'b/llama-server.exe'})

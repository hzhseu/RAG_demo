"""Optional local model catalog for the playground, separate from RAG config."""
import json
import hashlib
from functools import lru_cache
from pathlib import Path
from .config import asset
from .util import digest

from pydantic import BaseModel, ConfigDict, Field


class ModelEntry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    name: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r'^[a-fA-F0-9]{64}$')
    context: int = Field(default=8192, ge=512, le=131072)
    threads: int = Field(default=4, ge=1, le=256)
    llama_server: str | None = None
    generation: dict = Field(default_factory=lambda: {"temperature": .1})
    chat_template_kwargs: dict = Field(default_factory=dict)
    revision: str | None = None
    source: str | None = None


class Registry(dict):
    default_id = 'default'


def load_models(cfg, path=None):
    auto = path is None
    models = Registry({'default': {'id': 'default', 'name': 'Qwen3-4B-Instruct-2507', 'cfg': dict(cfg)}})
    if path is None:
        shared = Path(cfg.get('root', '.')) / 'chat-models.json'
        if cfg.get('root') and shared.is_file():
            path = shared
        else:
            legacy=Path(cfg.get('root','.'))/'model-test-models.json'
            return load_models(cfg,legacy) if cfg.get('root') and legacy.is_file() else models
    path = Path(path).resolve()
    raw = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(raw, dict) or not isinstance(raw.get('models'), list):
        raise ValueError('模型列表必须包含 models 数组')
    seen=set()
    for value in raw['models']:
        entry = ModelEntry.model_validate(value)
        if entry.id in seen or entry.id in models and not (entry.id == 'default' and 'default_model' in raw):
            raise ValueError(f'模型 ID 重复：{entry.id}')
        seen.add(entry.id)
        config = dict(cfg)
        config.update(chat_model=str((path.parent / entry.path).resolve()),
                      chat_model_sha256=entry.sha256.lower(), context=entry.context, threads=entry.threads,
                      model_id=entry.id, model_name=entry.name, generation=entry.generation,
                      chat_template_kwargs=entry.chat_template_kwargs)
        if entry.llama_server:
            config['llama_server'] = str((path.parent / entry.llama_server).resolve())
        models[entry.id] = {'id': entry.id, 'name': entry.name, 'cfg': config}
    models.default_id = raw.get('default_model', 'default')
    if models.default_id not in models:
        raise ValueError('默认模型不在注册表中')
    if auto:
        legacy = Path(cfg['root']) / 'model-test-models.json'
        if legacy.is_file():
            extra=load_models(cfg,legacy)
            for key,value in extra.items():
                if key == 'default':continue
                if key in models:raise ValueError(f'模型 ID 重复：{key}')
                models[key]=value
    return models


def model_options(models):
    return [{'id': key, 'name': entry['name'], 'file': Path(entry['cfg']['chat_model']).name,
             'context': entry['cfg'].get('context', 8192), 'threads': entry['cfg'].get('threads', 4)}
            for key, entry in models.items()]


@lru_cache(maxsize=32)
def _engine_digest(files):
    return hashlib.sha256(json.dumps({Path(name).name:digest(Path(name)) for name,size,mtime in files},sort_keys=True).encode()).hexdigest()


def engine_fingerprint(cfg):
    if not cfg.get('llama_server'):return None
    server=asset(cfg,'llama_server')
    if not server.is_file():return None
    files=sorted({server.resolve(), *(p.resolve() for p in server.parent.glob('*.dll'))})
    return _engine_digest(tuple((str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in files))


def identity(cfg):
    return {'id': cfg.get('model_id', 'default'), 'name': cfg.get('model_name', 'Qwen3-4B-Instruct-2507'),
            'file': Path(cfg['chat_model']).name, 'sha256': cfg.get('chat_model_sha256'),
            'generation': cfg.get('generation', {'temperature': .1}),
            'chat_template_kwargs': cfg.get('chat_template_kwargs', {}),
            'context': cfg.get('context', 8192), 'threads': cfg.get('threads', 4),
            'engine': Path(cfg.get('llama_server','llama-server.exe')).name, 'engine_sha256':engine_fingerprint(cfg)}


def unavailable_reason(cfg):
    for key in ('chat_model', 'llama_server'):
        if not cfg.get(key) or not asset(cfg, key).is_file():
            return f'缺少 {key}: {cfg.get(key)}'
    if digest(asset(cfg, 'chat_model')) != cfg.get('chat_model_sha256'):
        return '回答模型 SHA256 校验失败'
    return None

"""Optional local model catalog for the playground, separate from RAG config."""
import json
from pathlib import Path

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


def load_models(cfg, path=None):
    models = {'default': {'id': 'default', 'name': Path(cfg['chat_model']).name, 'cfg': dict(cfg)}}
    if path is None:
        return models
    path = Path(path).resolve()
    raw = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(raw, dict) or not isinstance(raw.get('models'), list):
        raise ValueError('模型列表必须包含 models 数组')
    for value in raw['models']:
        entry = ModelEntry.model_validate(value)
        if entry.id in models:
            raise ValueError(f'模型 ID 重复：{entry.id}')
        config = dict(cfg)
        config.update(chat_model=str((path.parent / entry.path).resolve()),
                      chat_model_sha256=entry.sha256.lower(), context=entry.context, threads=entry.threads)
        if entry.llama_server:
            config['llama_server'] = str((path.parent / entry.llama_server).resolve())
        models[entry.id] = {'id': entry.id, 'name': entry.name, 'cfg': config}
    return models


def model_options(models):
    return [{'id': key, 'name': entry['name'], 'file': Path(entry['cfg']['chat_model']).name,
             'context': entry['cfg'].get('context', 8192), 'threads': entry['cfg'].get('threads', 4)}
            for key, entry in models.items()]

"""Serial model transactions sharing the application's cross-process operation lock."""
import threading
from fastapi import HTTPException
from .chat_models import load_models, identity, unavailable_reason
from .util import read_json, write_json


class ModelManager:
    def __init__(self, engines, home, busy, models=None, validator=unavailable_reason):
        self.engines, self.busy = engines, busy
        self.models = models if models is not None else load_models(engines.base_cfg)
        self.validator = validator
        self.sequence = 0
        self.state = 'idle'
        self.error = None
        self.guard = threading.RLock()
        self.settings_path = home / 'model-selection.json'
        self.availability = {}
        if models is None:
            for key,entry in self.models.items():
                try:self.availability[key]=validator(entry['cfg'])
                except (OSError,ValueError) as exc:self.availability[key]=str(exc)

    def check_sequence(self, sequence):
        if str(self.sequence) != str(sequence):
            raise HTTPException(409, {'code':'model_changed','message':'回答模型已切换，请刷新状态后重试'})

    def status(self):
        ident = self.engines.model_identity
        return {'model': self.models.get(ident['id'], {}).get('name', ident['id']),
                'model_id': ident['id'], 'model_identity': ident, 'model_sequence': self.sequence,
                'model_state': self.state, 'model_error': self.error}

    def options(self):
        result=[]
        for key, entry in self.models.items():
            # Hash validation is performed on every selection; list only reports last
            # verified status, without hashing gigabytes on each browser poll.
            from .config import asset
            cfg=entry['cfg']
            missing=next((f'缺少 {k}' for k in ('chat_model','llama_server') if not asset(cfg,k).is_file()),None)
            reason=missing or self.availability.get(key)
            result.append({'id':key,'name':entry['name'],'available':not reason,'error':reason})
        return result

    def switch(self, model_id, sequence, *, locked=False, on_ready=None):
        with self.guard:
            self.check_sequence(sequence)
            if model_id not in self.models:
                raise HTTPException(404,'模型不在配置列表中')
            if not locked and not self.busy.acquire(blocking=False):
                raise HTTPException(409,'请等待当前任务完成或先停止生成，再切换模型')
            try:
                return self._switch(model_id,on_ready)
            finally:
                if not locked:self.busy.release()

    def _switch(self, model_id,on_ready=None):
        cfg=self.models[model_id]['cfg']
        previous=dict(self.engines.cfg)
        previous_identity=self.engines.model_identity
        previous_state=self.state
        self.state='loading'
        try:
            reason=self.validator(cfg)
            self.availability[model_id]=reason
            if reason:raise ValueError(reason)
            self.engines.select_model(cfg)
            try:
                extra=on_ready() if on_ready else {}
                write_json(self.settings_path,{'model_id':model_id})
            except Exception as save_error:
                try:self.engines.select_model(previous)
                except Exception as rollback_error:
                    raise RuntimeError(f'保存选择失败：{save_error}；回退失败：{rollback_error}') from rollback_error
                raise
            self.sequence+=1
            self.state='ready';self.error=None
            return self.status() | extra
        except Exception as exc:
            changed=self.engines.model_identity != previous_identity
            if changed:self.sequence+=1
            self.state='error' if changed or getattr(self.engines,'chat_unavailable',False) else previous_state
            self.error=str(exc)
            raise HTTPException(422,f'模型切换失败：{exc}') from exc

    def restore(self):
        try:
            model_id=read_json(self.settings_path).get('model_id') if self.settings_path.exists() else getattr(self.models,'default_id','default')
            self.switch(model_id,str(self.sequence))
        except (HTTPException,OSError,ValueError) as exc:
            self.state='error'; self.error=str(getattr(exc,'detail',exc))

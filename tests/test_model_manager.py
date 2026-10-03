import pytest
from fastapi import HTTPException
from nordrag.model_manager import ModelManager
from nordrag.operations import OperationLock

class Engine:
    def __init__(self): self.cfg={'model_id':'default','chat_model':'old','chat_model_sha256':'a'*64}; self.fail=False; self.calls=[]
    def select_model(self,cfg):
        self.calls.append(cfg['model_id'])
        if self.fail: raise RuntimeError('load failed; old restored')
        self.cfg=cfg
    @property
    def model_identity(self): return {'id':self.cfg.get('model_id','default')}

def manager(tmp_path):
    e=Engine()
    models={'default':{'name':'Old','cfg':e.cfg},'new':{'name':'New','cfg':e.cfg|{'model_id':'new'}}}
    return ModelManager(e,tmp_path,OperationLock(tmp_path),models=models,validator=lambda cfg:None),e

def test_switch_transaction_and_stale_request(tmp_path):
    m,e=manager(tmp_path)
    result=m.switch('new','0')
    assert result['model_id']=='new' and result['model_sequence']==1
    assert (tmp_path/'model-selection.json').exists()
    with pytest.raises(HTTPException) as ex: m.check_sequence('0')
    assert ex.value.status_code==409

def test_failed_switch_preserves_identity_and_sequence(tmp_path):
    m,e=manager(tmp_path);e.fail=True
    with pytest.raises(HTTPException): m.switch('new','0')
    assert m.status()['model_id']=='default' and m.sequence==0
    assert not (tmp_path/'model-selection.json').exists()

def test_busy_and_invalid_target_never_stops_engine(tmp_path):
    m,e=manager(tmp_path);m.busy.acquire()
    try:
        with pytest.raises(HTTPException):m.switch('new','0')
    finally:m.busy.release()
    assert e.calls==[]
    m.validator=lambda cfg:'bad hash'
    with pytest.raises(HTTPException):m.switch('new','0')
    assert e.calls==[]


def test_persistence_and_rollback_failure_fails_closed(tmp_path,monkeypatch):
    import nordrag.model_manager as module
    m,e=manager(tmp_path);m.state='ready'
    def select(cfg):
        if cfg.get('model_id')!='new':raise RuntimeError('rollback failed, new model recovered')
        e.cfg=cfg
    e.select_model=select
    monkeypatch.setattr(module,'write_json',lambda *a:(_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(HTTPException):m.switch('new','0')
    assert m.state=='error'
    assert m.sequence==1
    with pytest.raises(HTTPException):m.check_sequence('0')


def test_new_session_failure_rolls_back_before_saving_choice(tmp_path):
    m,e=manager(tmp_path);m.state='ready'
    def fail_session():raise OSError('cannot save new session')
    with pytest.raises(HTTPException):m.switch('new','0',on_ready=fail_session)
    assert m.status()['model_id']=='default' and m.sequence==0
    assert not (tmp_path/'model-selection.json').exists()

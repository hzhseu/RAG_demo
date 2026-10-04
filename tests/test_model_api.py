from test_api import setup_client
from nordrag.model_manager import ModelManager
from test_model_manager import Engine
import pytest


@pytest.mark.parametrize('mode', ['knowledge', 'advanced'])
def test_session_model_binding_and_stale_requests(deck,tmp_path,mode):
    client,headers=setup_client(deck,tmp_path)
    e=client.app.state.engines
    e.cfg={'chat_model':'old','chat_model_sha256':'a'*64}
    e.select_model=lambda cfg:setattr(e,'cfg',cfg)
    e.__class__=type('ModelChatEngine',(type(e),),{'model_identity':property(lambda self:{'id':self.cfg.get('model_id','default'),'sha256':'a'*64})})
    models={'default':{'name':'Old','cfg':e.cfg},'new':{'name':'New','cfg':e.cfg|{'model_id':'new'}}}
    m=ModelManager(e,tmp_path,client.app.state.knowledge.busy,models=models,validator=lambda cfg:None)
    client.app.state.models=m
    client.app.state.knowledge.active.app.state.models=m
    headers|={'X-Model-Sequence':'0'}
    old=client.post('/api/sessions',json={},headers=headers).json()
    assert old['model']['id']=='default'
    switched=client.post('/api/models/switch',json={'id':'new','mode':mode},headers=headers)
    assert switched.status_code==200,switched.text
    assert switched.json()['session']['model']['id']=='new'
    assert switched.json()['session']['mode']==mode
    assert client.post('/api/chat',headers=headers,json={'session_id':old['id'],'question':'hi'}).status_code==409
    headers['X-Model-Sequence']='1'
    resumed=client.post('/api/sessions/'+old['id']+'/activate',headers=headers)
    assert resumed.status_code==200,resumed.text
    assert m.status()['model_id']=='default'
    assert resumed.json()['model']['id']=='default'


def test_changed_model_file_cannot_continue_bound_session(deck,tmp_path):
    client,headers=setup_client(deck,tmp_path)
    e=client.app.state.engines
    e.cfg={'chat_model':'old','chat_model_sha256':'a'*64}
    e.__class__=type('BoundEngine',(type(e),),{'model_identity':property(lambda self:{'id':'default','sha256':self.cfg['chat_model_sha256']})})
    session=client.post('/api/sessions',json={},headers=headers).json()
    e.cfg['chat_model_sha256']='b'*64
    response=client.post('/api/chat',headers=headers,json={'session_id':session['id'],'question':'Hi'})
    assert response.status_code==409

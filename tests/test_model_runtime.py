import json, threading
import httpx
import pytest
from nordrag.engines import LlamaServer


def test_shared_stream_uses_profile_and_checks_completion():
    seen=[]
    def respond(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200,text='data: {"choices":[{"delta":{"content":"答案"}}]}\n\ndata: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    s=LlamaServer({'generation':{'temperature':.7},'chat_template_kwargs':{'enable_thinking':False}},'chat_model')
    s.client=httpx.Client(transport=httpx.MockTransport(respond),base_url='http://test')
    s.start=lambda:s
    assert ''.join(s.stream([{'role':'user','content':'你好'}],threading.Event()))=='答案'
    assert seen[0]['temperature']==.7
    assert seen[0]['chat_template_kwargs']=={'enable_thinking':False}
    s.client.close()


def test_stream_rejects_truncated_response():
    s=LlamaServer({},'chat_model')
    s.client=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')),base_url='http://test')
    s.start=lambda:s
    with pytest.raises(RuntimeError): list(s.stream([],threading.Event()))
    s.client.close()


def test_engine_recovers_old_worker_on_start_failure(monkeypatch,tmp_path):
    import nordrag.engines as module
    from nordrag.engines import Engines
    monkeypatch.setattr(module,'preflight',lambda *a:[])
    monkeypatch.setattr(module,'unavailable_reason',lambda cfg:None)
    events=[]
    class Server:
        def __init__(self,cfg,*a):self.cfg=cfg
        def start(self):
            events.append(('start',self.cfg['chat_model']))
            if self.cfg['chat_model']=='broken':raise RuntimeError('bad weights')
        def stop(self):events.append(('stop',self.cfg['chat_model']))
    monkeypatch.setattr(module,'LlamaServer',Server)
    cfg={'root':str(tmp_path),'chat_model':'old','chat_model_sha256':'a'*64,'embedding_model_sha256':'b'*64}
    e=Engines(cfg)
    with pytest.raises(RuntimeError,match='已恢复旧模型'):e.select_model(cfg|{'chat_model':'broken'})
    assert e.cfg['chat_model']=='old'
    assert events[-1]==('start','old') and not e.chat_unavailable


def test_bad_hash_does_not_release_old_worker(monkeypatch,tmp_path):
    import nordrag.engines as module
    from nordrag.engines import Engines
    monkeypatch.setattr(module,'preflight',lambda *a:[])
    events=[]
    class Server:
        def __init__(self,*a):pass
        def stop(self):events.append('stopped')
    monkeypatch.setattr(module,'LlamaServer',Server)
    e=Engines({'root':str(tmp_path),'chat_model':'old','chat_model_sha256':'a'*64,'embedding_model_sha256':'b'*64})
    monkeypatch.setattr(module,'unavailable_reason',lambda cfg:'SHA256 mismatch')
    with pytest.raises(ValueError):e.select_model({})
    assert events==[]

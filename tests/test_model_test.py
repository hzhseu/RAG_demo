"""Exercise the standalone API; only the external llama process is replaced."""
import importlib.util
import json
import threading
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient


def test_standalone_entry_exists():
    assert importlib.util.find_spec('nordrag.model_test') is not None, 'Standalone model tester is missing'


class LocalModel:
    process = None

    def __init__(self, *, large=False, broken=False, block=False):
        self.large, self.broken, self.block = large, broken, block
        self.started = threading.Event()
        self.release = threading.Event()
        self.payloads = []
        self.client = httpx.Client(transport=httpx.MockTransport(self.respond), base_url='http://127.0.0.1')

    def start(self):
        self.started.set()
        if self.block:
            assert self.release.wait(5)
        return self

    def stop(self):
        pass

    def count(self, text):
        return 9000 if self.large else 100

    def respond(self, request):
        data = json.loads(request.content)
        if request.url.path == '/apply-template':
            self.payloads.append(data['messages'])
            return httpx.Response(200, json={'prompt': 'formatted prompt'})
        if self.broken:
            return httpx.Response(500, text='model failed')
        self.payloads.append(data)
        chunks = [
            {'choices': [{'delta': {'content': '测试'}, 'finish_reason': None}]},
            {'choices': [{'delta': {'content': '结果'}, 'finish_reason': None}]},
            {'choices': [{'delta': {}, 'finish_reason': 'length'}]},
            {'choices': [], 'usage': {'prompt_tokens': 100, 'completion_tokens': 4}},
        ]
        return httpx.Response(200, text=''.join('data: ' + json.dumps(c) + '\n\n' for c in chunks) + 'data: [DONE]\n\n')


def make_client(tmp_path, model=None):
    from nordrag.model_test import create_app
    cfg = {'root': str(tmp_path), 'chat_model': 'chat.gguf', 'threads': 4, 'context': 8192}
    return TestClient(create_app(cfg, token='secret', server=model or LocalModel()))


HEADERS = {'X-Nord-Token': 'secret'}


def result(client, job_id):
    for _ in range(200):
        data = client.get('/api/tests/' + job_id, headers=HEADERS).json()
        if data['status'] in ('done', 'cancelled', 'error'):
            return data
        time.sleep(.01)
    raise AssertionError('Job did not finish')


def test_no_knowledge_or_other_model_required(tmp_path):
    with make_client(tmp_path) as client:
        info = client.get('/api/status', headers=HEADERS).json()
        assert info['model'] == 'chat.gguf'
        response = client.post('/api/tests', headers=HEADERS, json={'mode': 'chat', 'question': '你好'})
        assert response.status_code == 200
        record = result(client, response.json()['id'])
        assert record['text'] == '测试结果'
        assert record['status'] == 'done'
        assert record['finish_reason'] == 'length'
        assert record['output_tokens'] == 4
        assert record['first_token_seconds'] >= 0
        assert record['load_seconds'] >= 0
        assert record['request']['question'] == '你好'


@pytest.mark.parametrize('mode', ['grounded', 'summary'])
def test_material_reaches_model_without_retrieval(tmp_path, mode):
    model = LocalModel()
    with make_client(tmp_path, model) as client:
        response = client.post('/api/tests', headers=HEADERS, json={
            'mode': mode, 'material': '维修周期是30天。', 'question': '周期多久？',
            'instruction': '用一句话回答', 'max_tokens': 100,
        })
        record = result(client, response.json()['id'])
        assert record['status'] == 'done'
        payload = model.payloads[-1]
        assert '维修周期是30天。' in payload['messages'][-1]['content']
        assert '用一句话回答' in payload['messages'][-1]['content']
        assert payload['max_tokens'] == 100
        assert payload['temperature'] == .1


@pytest.mark.parametrize('body', [
    {'mode': 'chat', 'question': '  '}, {'mode': 'grounded', 'question': '问题'},
    {'mode': 'summary', 'material': ' '}, {'mode': 'other', 'question': '问题'},
    {'mode': 'chat', 'question': '问题', 'max_tokens': 9000},
])
def test_invalid_input_rejected_before_generation(tmp_path, body):
    with make_client(tmp_path) as client:
        assert client.post('/api/tests', headers=HEADERS, json=body).status_code == 422


def test_local_api_requires_token_and_same_origin(tmp_path):
    with make_client(tmp_path) as client:
        assert client.get('/api/status').status_code == 403
        assert client.get('/api/status', headers=HEADERS | {'Origin': 'https://elsewhere.example'}).status_code == 403
        assert client.get('/api/status', headers=HEADERS | {'Host': 'elsewhere.example'}).status_code == 403


def test_oversized_prompt_reports_error_and_allows_retry(tmp_path):
    model = LocalModel(large=True)
    with make_client(tmp_path, model) as client:
        response = client.post('/api/tests', headers=HEADERS, json={'mode': 'chat', 'question': 'hello'})
        record = result(client, response.json()['id'])
        assert record['status'] == 'error'
        assert '上下文' in record['error']
        model.large = False
        response = client.post('/api/tests', headers=HEADERS, json={'mode': 'chat', 'question': 'retry'})
        assert result(client, response.json()['id'])['status'] == 'done'


def test_cancel_during_loading_and_busy_conflict(tmp_path):
    model = LocalModel(block=True)
    with make_client(tmp_path, model) as client:
        body = {'mode': 'chat', 'question': 'hello'}
        job = client.post('/api/tests', headers=HEADERS, json=body).json()['id']
        assert model.started.wait(2)
        assert client.post('/api/tests', headers=HEADERS, json=body).status_code == 409
        assert client.post('/api/tests/' + job + '/cancel', headers=HEADERS).status_code == 200
        model.release.set()
        assert result(client, job)['status'] == 'cancelled'
        assert not model.payloads
        assert client.get('/api/status', headers=HEADERS).json()['busy'] is False


def test_model_failure_is_visible_not_a_successful_answer(tmp_path):
    with make_client(tmp_path, LocalModel(broken=True)) as client:
        job = client.post('/api/tests', headers=HEADERS, json={'mode': 'chat', 'question': 'hello'}).json()['id']
        record = result(client, job)
        assert record['status'] == 'error'
        assert record['error']


def test_chat_only_validation_does_not_need_embedding_ocr_or_office(tmp_path):
    from nordrag.model_test import validate_runtime
    from nordrag.util import digest
    (tmp_path / 'chat.gguf').write_bytes(b'model')
    (tmp_path / 'llama-server.exe').write_bytes(b'exe')
    cfg = {'root': str(tmp_path), 'chat_model': 'chat.gguf', 'llama_server': 'llama-server.exe',
           'chat_model_sha256': digest(tmp_path / 'chat.gguf')}
    validate_runtime(cfg)
    (tmp_path / 'chat.gguf').write_bytes(b'changed')
    with pytest.raises(ValueError, match='校验'):
        validate_runtime(cfg)


def new_session(client, model_id='default'):
    response = client.post('/api/sessions', headers=HEADERS, json={'model_id': model_id})
    assert response.status_code == 200, response.text
    return response.json()['id']


def send(client, session_id, **values):
    response = client.post('/api/tests', headers=HEADERS, json={'session_id': session_id, **values})
    assert response.status_code == 200, response.text
    return result(client, response.json()['id'])


def test_followup_sends_previous_user_and_assistant_turns(tmp_path):
    with make_client(tmp_path) as client:
        sid = new_session(client)
        send(client, sid, question='我的项目代号是松鼠。')
        followup = send(client, sid, question='我的项目代号是什么？')
        assert [m['role'] for m in followup['messages']] == ['system', 'user', 'assistant', 'user']
        assert followup['messages'][1]['content'] == '我的项目代号是松鼠。'
        assert followup['messages'][2]['content'] == '测试结果'
        assert followup['messages'][3]['content'] == '我的项目代号是什么？'
        session = client.get('/api/sessions/' + sid, headers=HEADERS).json()
        assert len(session['turns']) == 2
        assert session['messages'][-1] == {'role': 'assistant', 'content': '测试结果'}


@pytest.mark.parametrize('mode', ['summary', 'grounded'])
def test_material_and_summary_followups_keep_original_material(tmp_path, mode):
    with make_client(tmp_path) as client:
        sid = new_session(client)
        send(client, sid, mode=mode, material='维修周期是30天。', question='周期多久？')
        record = send(client, sid, mode=mode, question='请改写成一句英文。')
        assert record['status'] == 'done'
        assert '维修周期是30天。' in record['messages'][1]['content']
        assert record['messages'][-1]['content'] == '请改写成一句英文。'


def test_new_session_isolated_and_old_session_can_resume(tmp_path):
    with make_client(tmp_path) as client:
        first = new_session(client)
        send(client, first, question='记住代号松鼠')
        second = new_session(client)
        record = send(client, second, question='你好')
        assert len(record['messages']) == 2
        assert '松鼠' not in str(record['messages'])
        assert client.post('/api/tests', headers=HEADERS, json={'session_id': first, 'question': '追问'}).status_code == 409
        assert client.post('/api/sessions/' + first + '/activate', headers=HEADERS).status_code == 200
        assert len(send(client, first, question='再说一遍')['messages']) == 4
        assert client.get('/api/status', headers=HEADERS).json()['session_id'] == first


def test_failed_turn_not_added_to_conversation_and_history_not_silently_trimmed(tmp_path):
    model = LocalModel()
    with make_client(tmp_path, model) as client:
        sid = new_session(client)
        send(client, sid, question='记住原始问题')
        model.large = True
        failed = send(client, sid, question='这轮超限')
        assert failed['status'] == 'error'
        model.large = False
        next_turn = send(client, sid, question='下一轮')
        assert len(next_turn['messages']) == 4
        assert '记住原始问题' in str(next_turn['messages'])
        assert '这轮超限' not in str(next_turn['messages'])


def test_cancelled_turn_not_added_and_cannot_change_session_while_busy(tmp_path):
    model = LocalModel(block=True)
    with make_client(tmp_path, model) as client:
        sid = new_session(client)
        job = client.post('/api/tests', headers=HEADERS, json={'session_id': sid, 'question': '取消的输入'}).json()['id']
        assert model.started.wait(2)
        assert client.post('/api/sessions', headers=HEADERS, json={}).status_code == 409
        client.post('/api/tests/' + job + '/cancel', headers=HEADERS)
        model.release.set()
        assert result(client, job)['status'] == 'cancelled'
        record = send(client, sid, question='新的输入')
        assert len(record['messages']) == 2
        assert '取消的输入' not in str(record['messages'])


def test_cannot_change_mode_or_material_mid_conversation(tmp_path):
    with make_client(tmp_path) as client:
        sid = new_session(client)
        send(client, sid, mode='grounded', material='原文', question='概括原文')
        for body in ({'mode': 'chat', 'question': '问题'}, {'mode': 'grounded', 'material': '替换原文', 'question': '问题'}):
            assert client.post('/api/tests', headers=HEADERS, json={'session_id': sid, **body}).status_code == 409


def test_session_export_and_delete(tmp_path):
    with make_client(tmp_path) as client:
        sid = new_session(client)
        send(client, sid, question='第一轮')
        send(client, sid, question='第二轮')
        snapshot = client.get('/api/sessions/' + sid, headers=HEADERS).json()
        assert snapshot['model_id'] == 'default'
        assert [r['request']['question'] for r in snapshot['turns']] == ['第一轮', '第二轮']
        assert client.delete('/api/sessions/' + sid, headers=HEADERS).status_code == 200
        assert client.get('/api/sessions/' + sid, headers=HEADERS).status_code == 404


def test_model_catalog_paths_and_switching_preserve_sessions(tmp_path):
    from nordrag.model_test import create_app
    from nordrag.model_test_models import load_models
    from nordrag.util import digest
    configs = tmp_path / 'configs'
    configs.mkdir()
    (tmp_path / 'chat.gguf').write_bytes(b'default')
    (configs / 'other.gguf').write_bytes(b'other')
    (tmp_path / 'llama.exe').write_bytes(b'exe')
    cfg = {'root': str(tmp_path), 'chat_model': 'chat.gguf', 'llama_server': 'llama.exe', 'chat_model_sha256': digest(tmp_path / 'chat.gguf')}
    catalog_path = configs / 'model-test-models.json'
    catalog_path.write_text(json.dumps({'models': [{'id': 'other', 'name': '另一个模型', 'path': 'other.gguf', 'sha256': digest(configs / 'other.gguf'), 'context': 4096}]}), encoding='utf-8')
    catalog = load_models(cfg, catalog_path)
    old = LocalModel()
    stopped = threading.Event()
    old.stop = stopped.set
    selected = []
    def factory(config):
        selected.append(config)
        return LocalModel()
    with TestClient(create_app(cfg, token='secret', server=old, models=catalog, server_factory=factory)) as client:
        first = new_session(client)
        send(client, first, question='默认模型的对话')
        second = new_session(client, 'other')
        assert stopped.is_set()
        assert Path(selected[-1]['chat_model']) == configs / 'other.gguf'
        assert selected[-1]['context'] == 4096
        response = send(client, second, question='不同模型')
        assert response['model'] == 'other.gguf'
        assert len(response['messages']) == 2
        assert client.post('/api/sessions/' + first + '/activate', headers=HEADERS).status_code == 200
        assert len(send(client, first, question='继续')['messages']) == 4
        (configs / 'other.gguf').write_bytes(b'corrupted')
        assert client.post('/api/sessions', headers=HEADERS, json={'model_id': 'other'}).status_code == 422
        assert client.get('/api/status', headers=HEADERS).json()['session_id'] == first


def test_invalid_catalog_is_rejected(tmp_path):
    from nordrag.model_test_models import load_models
    path = tmp_path / 'models.json'
    path.write_text(json.dumps({'models': [{'id': 'default', 'name': 'duplicate', 'path': 'x', 'sha256': '0' * 64}]}), encoding='utf-8')
    with pytest.raises(ValueError, match='重复'):
        load_models({'root': str(tmp_path), 'chat_model': 'chat.gguf'}, path)

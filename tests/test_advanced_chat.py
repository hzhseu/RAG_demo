import json

import pytest

from test_api import setup_client
from nordrag.util import read_json, write_json


def chat_events(client, headers, sid, question='解释一下这个概念'):
    response = client.post('/api/chat', headers=headers,
                           json={'session_id': sid, 'question': question})
    assert response.status_code == 200, response.text
    return [json.loads(line[6:]) for line in response.text.splitlines()
            if line.startswith('data: ')]


@pytest.mark.parametrize('has_evidence', [False, True])
def test_advanced_accepts_general_knowledge_without_claiming_document_support(deck, tmp_path, monkeypatch, has_evidence):
    client, headers = setup_client(deck, tmp_path)
    session = client.post('/api/sessions', headers=headers, json={'mode': 'advanced'}).json()
    if not has_evidence:
        monkeypatch.setattr('nordrag.api.retrieve', lambda *args: [])
    answer = '通用知识补充：可以从原理、适用条件和限制三个方面分析。'
    monkeypatch.setattr(client.app.state.engines, 'stream', lambda *args: iter([answer]))
    done = next(e for e in chat_events(client, headers, session['id']) if e['type'] == 'done')
    assert done['text'] == answer
    assert done['mode'] == 'advanced'
    assert done['supported'] is False
    assert done['citation_valid'] is True
    saved = client.get('/api/sessions/' + session['id'], headers=headers).json()
    assert saved['mode'] == 'advanced'
    assert saved['messages'][-1]['citation_valid'] is True
    assert saved['messages'][-1]['mode'] == 'advanced'
    assert bool(done['citations']) is has_evidence


@pytest.mark.parametrize('answer', ['假引用 [99]', '伪统计 [项目统计]', ''])
def test_advanced_blocks_invalid_answers(deck, tmp_path, monkeypatch, answer):
    client, headers = setup_client(deck, tmp_path)
    sid = client.post('/api/sessions', headers=headers, json={'mode': 'advanced'}).json()['id']
    monkeypatch.setattr(client.app.state.engines, 'stream', lambda *args: iter([answer]))
    done = next(e for e in chat_events(client, headers, sid) if e['type'] == 'done')
    assert done['text'] != answer
    assert done['citation_valid'] is False
    assert done['supported'] is False


def test_legacy_sessions_remain_strict_and_modes_are_validated(deck, tmp_path, monkeypatch):
    client, headers = setup_client(deck, tmp_path)
    assert client.post('/api/sessions', headers=headers, json={'mode': 'unknown'}).status_code == 422
    session = client.post('/api/sessions', headers=headers, json={}).json()
    path = tmp_path / 'data' / 'sessions' / (session['id'] + '.json')
    legacy = read_json(path)
    legacy.pop('mode', None)
    write_json(path, legacy)
    assert client.get('/api/sessions', headers=headers).json()[0]['mode'] == 'knowledge'
    resumed = client.post('/api/sessions/' + session['id'] + '/activate', headers=headers).json()
    assert resumed['mode'] == 'knowledge'
    monkeypatch.setattr(client.app.state.engines, 'stream', lambda *args: iter(['无引用的回答']))
    done = next(e for e in chat_events(client, headers, session['id']) if e['type'] == 'done')
    assert done['text'] != '无引用的回答'
    assert done['supported'] is False


def test_advanced_catalog_uses_verified_totals_and_topic_cannot_enter_advanced_history(deck, tmp_path):
    client, headers = setup_client(deck, tmp_path)
    sid = client.post('/api/sessions', headers=headers, json={'mode': 'advanced'}).json()['id']
    done = next(e for e in chat_events(client, headers, sid, '有多少文档？') if e['type'] == 'done')
    assert done['answer_source']['type'] == 'catalog'
    assert done['supported'] is True
    assert done['mode'] == 'advanced'
    docs = client.get('/api/documents', headers=headers).json()
    response = client.post('/api/topic', headers=headers,
                           json={'session_id': sid, 'document_ids': [docs[0]['id']]})
    assert response.status_code == 409


def test_advanced_retrieval_error_is_not_silently_replaced_by_general_knowledge(deck, tmp_path, monkeypatch):
    client, headers = setup_client(deck, tmp_path)
    sid = client.post('/api/sessions', headers=headers, json={'mode': 'advanced'}).json()['id']
    def fail(*args):
        raise RuntimeError('检索失败')
    monkeypatch.setattr('nordrag.api.retrieve', fail)
    events = chat_events(client, headers, sid)
    assert any(e['type'] == 'error' and e['message'] == '检索失败' for e in events)
    assert not any(e['type'] == 'done' for e in events)
    assert client.get('/api/sessions/' + sid, headers=headers).json()['messages'] == []

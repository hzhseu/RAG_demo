import json

from test_api import setup_client
from nordrag.util import read_json, write_json


def done(response):
    return next(json.loads(line[6:]) for line in response.text.splitlines()
                if line.startswith('data: ') and json.loads(line[6:])['type'] == 'done')


def test_default_session_and_explicit_hybrid_and_legacy(deck, tmp_path):
    client, headers = setup_client(deck, tmp_path)
    session = client.post('/api/sessions', json={}, headers=headers).json()
    assert session['retrieval_mode'] == 'rerank'
    hybrid = client.post('/api/sessions', json={'retrieval_mode':'hybrid'}, headers=headers).json()
    assert hybrid['retrieval_mode'] == 'hybrid'
    assert client.post('/api/sessions', json={'retrieval_mode':'bad'}, headers=headers).status_code == 422
    path = tmp_path/'data'/'sessions'/f"{session['id']}.json"
    saved = read_json(path); saved.pop('retrieval_mode'); write_json(path, saved)
    restored = client.post(f"/api/sessions/{session['id']}/activate", headers=headers).json()
    assert restored['retrieval_mode'] == 'hybrid'


def test_rerank_mode_persists_actual_ranking_and_timing(deck, tmp_path):
    client, headers = setup_client(deck, tmp_path)
    engine = client.app.state.engines
    engine.rerank = lambda q, chunks, cancel: [float(i) for i in range(len(chunks))]
    session = client.post('/api/sessions', json={'mode':'advanced'}, headers=headers).json()
    response = client.post('/api/chat', json={'session_id':session['id'], 'question':'Alpha 保修'}, headers=headers)
    event = done(response)
    assert event['retrieval_mode'] == 'rerank' and not event['rerank_fallback']
    assert event['rerank_seconds'] >= 0 and event['rerank_reason'] is None
    assert 'rerank_score' in event['citations'][0]
    assert '正在重排证据' in response.text
    saved = client.get(f"/api/sessions/{session['id']}", headers=headers).json()['messages'][-1]
    assert saved['retrieval_mode'] == event['retrieval_mode']
    assert saved['rerank_seconds'] == event['rerank_seconds']


def test_missing_model_fallback_is_visible_and_stored(deck, tmp_path):
    client, headers = setup_client(deck, tmp_path)
    session = client.post('/api/sessions', json={}, headers=headers).json()
    response = client.post('/api/chat', json={'session_id':session['id'], 'question':'Alpha 保修'}, headers=headers)
    event = done(response)
    assert event['rerank_fallback'] and event['retrieval_mode'] == 'hybrid'
    assert event['rerank_reason'] == 'model_missing'
    assert '已使用原混合检索' in response.text


def test_catalog_and_hybrid_do_not_call_reranker(deck, tmp_path):
    client, headers = setup_client(deck, tmp_path)
    def unexpected(*args): raise AssertionError('must bypass reranker')
    client.app.state.engines.rerank = unexpected
    for retrieval, question, actual in [('rerank','知识库有多少文档？','not_applicable'), ('hybrid','Alpha 保修','hybrid')]:
        session = client.post('/api/sessions', json={'retrieval_mode':retrieval}, headers=headers).json()
        event = done(client.post('/api/chat', json={'session_id':session['id'],'question':question}, headers=headers))
        assert event['retrieval_mode'] == actual and event['rerank_seconds'] == 0


def test_cancellation_during_rerank_does_not_generate_or_save(deck, tmp_path):
    from nordrag.reranking import RerankCancelled
    client, headers = setup_client(deck, tmp_path)
    def cancelled(query, chunks, event):
        event.set()
        raise RerankCancelled('任务已取消')
    def unexpected(*args): raise AssertionError('must not generate after cancellation')
    client.app.state.engines.rerank = cancelled
    client.app.state.engines.stream = unexpected
    session = client.post('/api/sessions', json={}, headers=headers).json()
    response = client.post('/api/chat', json={'session_id':session['id'],'question':'Alpha 保修'}, headers=headers)
    events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert any(e['type']=='cancelled' for e in events)
    assert not any(e['type']=='done' for e in events)
    assert client.get(f"/api/sessions/{session['id']}",headers=headers).json()['messages'] == []


def test_topic_bypasses_rerank_with_rerank_session(deck, tmp_path):
    client, headers = setup_client(deck, tmp_path)
    def unexpected(*args): raise AssertionError('topic must not rerank')
    client.app.state.engines.rerank = unexpected
    session=client.post('/api/sessions',json={},headers=headers).json()
    docs=client.get('/api/documents',headers=headers).json()
    event=done(client.post('/api/topic',json={'session_id':session['id'],'document_ids':[docs[0]['id']]},headers=headers))
    assert event['retrieval_mode']=='not_applicable' and event['rerank_seconds']==0

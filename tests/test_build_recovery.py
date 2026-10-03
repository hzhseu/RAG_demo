import threading
import httpx
import pytest
from nordrag import engines as module


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(module, 'preflight', lambda *args: [])
    class Server:
        def __init__(self, *args): self.stops = 0
        def stop(self): self.stops += 1
    monkeypatch.setattr(module, 'LlamaServer', Server)
    return module.Engines({'chat_model':'chat', 'chat_model_sha256':'abc',
                          'embedding_model_sha256':'xyz'}, build=True)


def test_timeout_restarts_model_and_retries_with_smaller_context(engine, monkeypatch):
    budgets, progress = [], []
    def summary(model, chunks, cancel, **kwargs):
        budgets.append(kwargs.get('budget', 6500))
        if len(budgets) == 1: raise httpx.ReadTimeout('timed out')
        return {'summary':'有依据的事实 [1]', 'citations':[{'id':'one'}]}
    monkeypatch.setattr(module, 'summarize_document', summary)
    engine.stream = lambda *args, **kwargs: iter(['{"category":"研究","tags":["无线"]}'])
    result = engine.organize_with_progress([{'id':'one'}], threading.Event(), progress.append)
    assert result['summary'] == '有依据的事实 [1]'
    assert budgets == [6500, 3250]
    assert engine.chat.stops == 1
    assert any(e['stage'] == 'retry' for e in progress)


def test_repeated_timeout_is_bounded_and_never_publishes_partial_summary(engine, monkeypatch):
    calls = []
    def summary(*args, **kwargs):
        calls.append(1)
        raise httpx.ReadTimeout('still timed out')
    monkeypatch.setattr(module, 'summarize_document', summary)
    with pytest.raises(httpx.ReadTimeout):
        engine.organize([], threading.Event())
    assert len(calls) == 2
    assert engine.chat.stops == 2


def test_invalid_evidence_is_not_retried(engine, monkeypatch):
    calls = []
    def summary(*args, **kwargs):
        calls.append(1)
        raise ValueError('摘要未产生有效引用')
    monkeypatch.setattr(module, 'summarize_document', summary)
    with pytest.raises(ValueError, match='引用'):
        engine.organize([], threading.Event())
    assert len(calls) == 1


def test_cancel_during_timeout_prevents_retry(engine, monkeypatch):
    cancel = threading.Event()
    calls = []
    def summary(*args, **kwargs):
        calls.append(1)
        cancel.set()
        raise httpx.ReadTimeout('timed out')
    monkeypatch.setattr(module, 'summarize_document', summary)
    with pytest.raises(RuntimeError, match='取消'):
        engine.organize([], cancel)
    assert len(calls) == 1


def test_retry_never_exceeds_small_context_budget(engine, monkeypatch):
    engine.cfg['context'] = 2048
    budgets = []
    def summary(*args, **kwargs):
        budgets.append(kwargs['budget'])
        raise httpx.ReadTimeout('timed out')
    monkeypatch.setattr(module, 'summarize_document', summary)
    with pytest.raises(httpx.ReadTimeout):
        engine.organize([], threading.Event())
    assert budgets[1] <= budgets[0]

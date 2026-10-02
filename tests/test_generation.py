import threading
from nordrag.generation import prepare_messages, checked_answer, summarize_document, summarize_topic


def test_evidence_budget_does_not_break_table_rows():
    chunks = [{"id": str(i), "text": "Revenue EUR | Alpha | 120.50 " * 100, "doc_id": "d", "page": i + 1, "kind": "table"} for i in range(20)]
    messages, evidence = prepare_messages("收入?", chunks, [], count=lambda s: len(s), budget=6500)
    assert 0 < len(evidence) < 20
    assert sum(len(m["content"]) for m in messages) <= 6500
    assert all(e["text"] == chunks[i]["text"] for i, e in enumerate(evidence))


def test_invalid_citation_is_not_published_as_supported():
    text, valid = checked_answer("Alpha costs 120.50 EUR [99]", [{"id": "a"}])
    assert not valid and "[99]" not in text
    text, valid = checked_answer("Alpha costs 120.50 EUR [1]", [{"id": "a"}])
    assert valid


def test_summary_covers_late_pages_without_silent_truncation():
    chunks = [{"id": str(i), "text": f"Fact on slide {i+1}. " * 100, "doc_id": "d", "page": i + 1, "kind": "text"} for i in range(12)]
    seen = []
    class Model:
        def count(self, text): return len(text)
        def stream(self, messages, cancel, max_tokens=768):
            seen.append(messages[-1]["content"])
            yield "Grounded summary [1]"
    summary = summarize_document(Model(), chunks, threading.Event())
    assert any("slide 12" in prompt for prompt in seen)
    assert summary["citations"]


def test_topic_summarizes_each_document_before_synthesis():
    chunks=[{'id':'a','doc_id':'one','doc_name':'One','page':1,'kind':'text','text':'Alpha warranty 24 months'}, {'id':'b','doc_id':'two','doc_name':'Two','page':2,'kind':'text','text':'Historical warranty 18 months'}]
    calls=[]
    class Model:
        def count(self,text):return len(text)
        def stream(self,messages,cancel,max_tokens=768):
            calls.append(messages[-1]['content'])
            yield 'Document finding [1]'
    result=summarize_topic(Model(),chunks,threading.Event())
    assert len(calls)==3
    assert 'Historical warranty' not in calls[0]
    assert 'Alpha warranty' not in calls[1]
    assert 'One' in calls[2] and 'Two' in calls[2]
    assert {c['doc_id'] for c in result['citations']}=={'one','two'}

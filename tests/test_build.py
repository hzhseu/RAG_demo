from pathlib import Path
import threading
import numpy as np
import pytest
from pypdf import PdfWriter
from nordrag.builder import build, BuildError
from nordrag.package import open_package
from nordrag.util import read_json


class Engines:
    """Only external inference/rendering is substituted; pipeline and archive are real."""
    embedding_id = "test-only-embedding"
    signature = "test-only-v1"

    def convert(self, source, target, pages):
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=720, height=540)
        with target.open("wb") as f:
            writer.write(f)

    def ocr(self, blob):
        return "Image recognition 测试 10%"

    def embed(self, texts, query=False):
        return np.array([[1., 0., 0.] for _ in texts])

    def organize(self, chunks, cancel):
        return {"summary": "Alpha 保修24个月 [1]", "category": "产品", "tags": ["保修"], "citations": chunks[:1]}


def test_build_survives_source_removal_and_reuses_cache(deck, tmp_path):
    e = Engines()
    cache = tmp_path / "cache"
    out = tmp_path / "first.ragkb"
    report = build(deck.parent, "Test", out, cache, e, threading.Event())
    assert report["status"] == "complete"
    e.convert = lambda *args: pytest.fail("successful parse cache should be reused")
    e.organize = lambda *args: pytest.fail("successful summary cache should be reused")
    build(deck.parent, "Test", tmp_path / "second.ragkb", cache, e, threading.Event())
    deck.unlink()
    root, m = open_package(out, tmp_path / "work", e.embedding_id)
    docs = read_json(root / "documents.json")
    assert len(docs) == 1 and (root / docs[0]["preview"]).exists()
    assert (root / docs[0]["source"]).exists()
    assert m["name"] == "Test"
    assert m["processing"]["chunk_max_chars"] == 1400
    assert m["processing"]["models_and_components"]["embedding"] == e.embedding_id


def test_failures_require_explicit_exclusion(deck, tmp_path):
    (deck.parent / "broken.pptx").write_bytes(b"invalid")
    out = tmp_path / "bad.ragkb"
    with pytest.raises(BuildError):
        build(deck.parent, "Test", out, tmp_path / "cache", Engines(), threading.Event())
    assert not out.exists()
    report = read_json(out.with_suffix(".report.json"))
    assert report["failed"][0]["path"] == "broken.pptx"
    result = build(deck.parent, "Test", out, tmp_path / "cache", Engines(), threading.Event(), excluded=["broken.pptx"])
    assert result["excluded"] == ["broken.pptx"]


def test_cancel_does_not_publish(deck, tmp_path):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(BuildError, match="取消"):
        build(deck.parent, "Test", tmp_path / "cancel.ragkb", tmp_path / "cache", Engines(), cancel)
    assert not (tmp_path / "cancel.ragkb").exists()

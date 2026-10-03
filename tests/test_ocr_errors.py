import json
import sys
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from nordrag import engines, ocr_worker
from nordrag.diagnostics import ComponentUnavailableError


@pytest.mark.parametrize('phase', ['initialize', 'document', 'resource'])
def test_worker_error_classification_reaches_builder(monkeypatch, phase):
    engine = object.__new__(engines.Engines)
    engine.cfg = {}
    monkeypatch.setattr(engines, 'asset', lambda cfg, key: key)
    def run(args, **kwargs):
        Path(args[3]).write_text(json.dumps({'stage': phase, 'error': 'specific OCR failure', 'error_type': 'RuntimeError'}), encoding='utf-8')
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(engines, 'run_owned', run)
    expected = RuntimeError if phase == 'document' else ComponentUnavailableError
    with pytest.raises(expected, match='specific OCR failure') as error:
        engine.ocr(b'image')
    if phase == 'document':
        assert not isinstance(error.value, ComponentUnavailableError)


@pytest.mark.parametrize('phase', ['initialize', 'document'])
def test_worker_reports_initialization_separately_from_bad_image(tmp_path, monkeypatch, phase):
    model = tmp_path / 'model'
    model.mkdir()
    output = tmp_path / 'result.json'
    source = tmp_path / 'image.bin'
    source.write_bytes(b'bad image')
    def create(**kwargs):
        if phase == 'initialize':
            raise RuntimeError('model load failed')
        return SimpleNamespace(predict=lambda image: [])
    monkeypatch.setitem(sys.modules, 'paddleocr', SimpleNamespace(PaddleOCR=create))
    monkeypatch.setattr(sys, 'argv', ['worker', str(source), str(output), str(model), str(model)])
    assert ocr_worker.main() == 1
    failure = json.loads(output.read_text(encoding='utf-8'))
    assert failure['stage'] == phase
    assert failure['error'] and failure['error_type']


@pytest.mark.parametrize('phase', ['initialize', 'document'])
def test_worker_timeout_classification_uses_last_stage(monkeypatch, phase):
    engine = object.__new__(engines.Engines)
    engine.cfg = {}
    monkeypatch.setattr(engines, 'asset', lambda cfg, key: key)
    def run(args, **kwargs):
        Path(args[3]).write_text(json.dumps({'stage': phase}), encoding='utf-8')
        raise subprocess.TimeoutExpired('ocr', 180)
    monkeypatch.setattr(engines, 'run_owned', run)
    expected = ComponentUnavailableError if phase == 'initialize' else subprocess.TimeoutExpired
    with pytest.raises(expected):
        engine.ocr(b'image')


def test_worker_success_preserves_recognized_text(tmp_path, monkeypatch):
    from PIL import Image
    source = tmp_path / 'image.png'
    Image.new('RGB', (8, 8), 'white').save(source)
    output = tmp_path / 'result.json'
    def create(**kwargs):
        return SimpleNamespace(predict=lambda image: [{'rec_texts': ['中文', 'English']}])
    monkeypatch.setitem(sys.modules, 'paddleocr', SimpleNamespace(PaddleOCR=create))
    monkeypatch.setattr(sys, 'argv', ['worker', str(source), str(output), str(tmp_path), str(tmp_path)])
    assert ocr_worker.main() == 0
    assert json.loads(output.read_text(encoding='utf-8')) == {'text': '中文\nEnglish'}

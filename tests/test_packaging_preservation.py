import pytest
from scripts import package_windows as packaging


@pytest.mark.parametrize('build_fails', [False, True])
def test_repackaging_preserves_entire_previous_release(tmp_path, monkeypatch, build_fails):
    root = tmp_path
    old = root / 'dist/NordRAG'
    (old / 'samples').mkdir(parents=True)
    (old / 'samples/wireless.ragkb').write_bytes(b'irreplaceable knowledge')
    (old / 'personal-notes.txt').write_text('user material')
    (root / 'frontend/dist').mkdir(parents=True)
    (root / 'frontend/dist/index.html').write_text('frontend')
    (root / 'docs').mkdir()
    (root / 'README.md').write_text('readme')
    (root / 'chat-models.json').write_text('{"default_model":"new","models":[]}')
    monkeypatch.setattr(packaging, 'ROOT', root)
    monkeypatch.setattr(packaging.sys, 'argv', ['package_windows.py', '--app-only'])

    def build(*args, **kwargs):
        # PyInstaller --noconfirm would recursively delete any existing target.
        assert not old.exists(), 'Previous release must be preserved before PyInstaller runs'
        if build_fails:
            raise RuntimeError('compiler failed')
        old.mkdir()
        (old / 'NordRAG.exe').write_bytes(b'application')
    monkeypatch.setattr(packaging.subprocess, 'run', build)
    if build_fails:
        with pytest.raises(RuntimeError, match='compiler failed'):
            packaging.main()
    else:
        packaging.main()
        assert (old / 'samples/wireless.ragkb').read_bytes() == b'irreplaceable knowledge'
    backups = list((root / 'dist/previous-releases').glob('NordRAG-*'))
    assert len(backups) == 1
    assert (backups[0] / 'samples/wireless.ragkb').read_bytes() == b'irreplaceable knowledge'
    assert (backups[0] / 'personal-notes.txt').read_text() == 'user material'


def test_conflicting_sample_is_preserved_without_overwriting_new_sample(tmp_path):
    previous = tmp_path / 'previous'
    target = tmp_path / 'new'
    for folder, content in ((previous, b'old knowledge'), (target, b'new sample')):
        (folder / 'samples').mkdir(parents=True)
        (folder / 'samples/demo.ragkb').write_bytes(content)
    packaging.restore_knowledge_files(previous, target)
    assert (target / 'samples/demo.ragkb').read_bytes() == b'new sample'
    assert (target / 'preserved-knowledge/samples/demo.ragkb').read_bytes() == b'old knowledge'


def test_custom_catalog_keeps_weights_and_engine_dlls(tmp_path):
    import json
    previous=tmp_path/'old';target=tmp_path/'new'
    (previous/'custom-engine').mkdir(parents=True);target.mkdir()
    (previous/'custom.gguf').write_bytes(b'custom model')
    (previous/'custom-engine/llama-server.exe').write_bytes(b'engine')
    (previous/'custom-engine/ggml.dll').write_bytes(b'dependency')
    (previous/'model-test-models.json').write_text(json.dumps({'models':[{'id':'custom','name':'Custom','path':'custom.gguf','sha256':'a'*64,'llama_server':'custom-engine/llama-server.exe'}]}))
    (target/'chat-models.json').write_text('{"default_model":"new","models":[]}')
    packaging.restore_model_catalogs(previous,target)
    entry=json.loads((target/'model-test-models.json').read_text())['models'][0]
    assert (target/entry['path']).read_bytes()==b'custom model'
    assert (target/entry['llama_server']).read_bytes()==b'engine'
    assert (target/entry['llama_server']).with_name('ggml.dll').read_bytes()==b'dependency'

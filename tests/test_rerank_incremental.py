import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows incremental updater')
SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/rerank_incremental/Apply-Update.ps1'


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def update_dirs(tmp_path):
    package, target = tmp_path / 'update', tmp_path / 'old application'
    package.mkdir()
    target.mkdir()
    shutil.copyfile(SCRIPT, package / SCRIPT.name)
    files = {'nord-chat.exe': b'new app', '_internal/base_library.zip': b'new library',
             'docs/RERANKING.md': b'new docs'}
    for name, data in files.items():
        for base, value in ((package / 'payload', data), (target, b'old ' + data)):
            path = base / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
    (target / '_internal/python313.dll').write_bytes(b'compatible dependency')
    manifest = dict(format=1, files={k: sha(v) for k, v in files.items()},
                    dependencies={'_internal/python313.dll': sha(b'compatible dependency')})
    (package / 'update-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    cfg = dict(reranker_model='custom/rank.gguf', reranker_candidates=30, reranker_top_k=8,
               chat_model='D:/custom/model.gguf', context=16384, generation={'temperature': .25}, enabled=False)
    (target / 'runtime.json').write_text(json.dumps(cfg), encoding='utf-8')
    (target / 'checksums.json').write_text(json.dumps({'custom-model': 'keep'}), encoding='utf-8')
    (target / 'my-library.ragkb').write_bytes(b'user knowledge')
    return package, target, cfg


def run_update(package, target):
    return subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                           '-File', str(package / SCRIPT.name), '-TargetDirectory', str(target)],
                          capture_output=True, encoding='utf-8', errors='replace', timeout=30)


def snapshot(target):
    return {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob('*')
            if p.is_file() and 'update-backups' not in p.parts}


def test_update_preserves_custom_configuration_and_creates_restorable_backup(update_dirs):
    package, target, cfg = update_dirs
    before = snapshot(target)
    result = run_update(package, target)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'SUCCESS' in result.stdout
    updated = json.loads((target / 'runtime.json').read_text(encoding='utf-8'))
    assert updated == {**cfg, 'reranker_candidates': 16}
    assert (target / 'my-library.ragkb').read_bytes() == before['my-library.ragkb']
    backup = next((target / 'update-backups').glob('*/files'))
    for p in backup.rglob('*'):
        if p.is_file():
            assert p.read_bytes() == before[p.relative_to(backup).as_posix()]
    checksums = json.loads((target / 'checksums.json').read_text(encoding='utf-8'))
    assert checksums['custom-model'] == 'keep'
    for name in ('nord-chat.exe', '_internal/base_library.zip', 'docs/RERANKING.md', 'runtime.json'):
        assert checksums[name] == sha((target / name).read_bytes())
    after = snapshot(target)
    again = run_update(package, target)
    assert again.returncode == 0, again.stdout + again.stderr
    assert snapshot(target) == after


@pytest.mark.parametrize('bad_file', ['payload/nord-chat.exe', 'dependency'])
def test_incompatible_or_damaged_update_leaves_installation_untouched(update_dirs, bad_file):
    package, target, _ = update_dirs
    path = target / '_internal/python313.dll' if bad_file == 'dependency' else package / bad_file
    path.write_bytes(b'damaged')
    before = snapshot(target)
    result = run_update(package, target)
    assert result.returncode != 0
    assert snapshot(target) == before
    assert not (target / 'update-backups').exists()


def test_update_restores_files_after_partial_commit_failure(update_dirs):
    package, target, _ = update_dirs
    script = package / SCRIPT.name
    text = script.read_text(encoding='utf-8')
    needle = '$written.Add($record)'
    assert text.count(needle) == 1
    # Simulate an I/O failure after replacing the EXE but before the second file.
    script.write_text(text.replace(needle, needle + "\n        if ($record.Name -eq '_internal/base_library.zip') { throw 'simulated disk error' }"), encoding='utf-8')
    before = snapshot(target)
    result = run_update(package, target)
    assert result.returncode != 0
    assert 'simulated disk error' in result.stdout
    assert 'Original files have been restored' in result.stdout
    assert snapshot(target) == before


def test_dependency_path_escape_is_rejected(update_dirs):
    package, target, _ = update_dirs
    path = package / 'update-manifest.json'
    manifest = json.loads(path.read_text())
    manifest['dependencies'] = {'_internal/../../outside': '0' * 64}
    path.write_text(json.dumps(manifest), encoding='utf-8')
    before = snapshot(target)
    result = run_update(package, target)
    assert result.returncode != 0
    assert snapshot(target) == before


def test_locked_application_is_not_replaced(update_dirs):
    import ctypes
    from ctypes import wintypes
    package, target, _ = update_dirs
    before = snapshot(target)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(target / 'nord-chat.exe'), 0x80000000, 0, None, 3, 0, None)
    assert handle != ctypes.c_void_p(-1).value
    try:
        result = run_update(package, target)
        assert result.returncode != 0
        assert not (target / 'update-backups').exists()
    finally:
        kernel.CloseHandle(handle)
    assert snapshot(target) == before

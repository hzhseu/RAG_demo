import json
import threading
import zipfile
from pathlib import Path
import pytest
from nordrag.package import seal, validate, PackageError
from nordrag.operations import OperationLock


def test_cross_process_style_lock_excludes_second_owner(tmp_path):
    a, b = OperationLock(tmp_path), OperationLock(tmp_path)
    assert a.acquire(blocking=False)
    try:
        assert not b.acquire(blocking=False)
    finally:
        a.release()
    assert b.acquire(blocking=False)
    b.release()


def test_package_rejects_windows_case_collision(tmp_path):
    p = tmp_path/'bad.ragkb'
    with zipfile.ZipFile(p,'w') as z:
        z.writestr('data.txt','a')
        z.writestr('DATA.TXT','b')
    with pytest.raises(PackageError):
        validate(p,'e')


@pytest.mark.parametrize('member',['a//b.txt','./b.txt','CON.txt','a/NUL'])
def test_package_rejects_ambiguous_windows_members(tmp_path, member):
    import hashlib
    from nordrag.package import content_version
    p=tmp_path/'ambiguous.ragkb'
    m={'format':1,'embedding':'e','files':{member:hashlib.sha256(b'bad').hexdigest()}}
    m['version']=content_version(m)
    with zipfile.ZipFile(p,'w') as z:
        z.writestr(member,'bad')
        z.writestr('manifest.json',json.dumps(m))
    with pytest.raises(PackageError,match='路径'):
        validate(p,'e')

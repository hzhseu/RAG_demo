from nordrag.workspace import clean_abandoned_work


def test_cleanup_only_removes_owned_work_directories(tmp_path):
    stale=tmp_path/('a'*20+'-old12345');stale.mkdir();(stale/'data').write_text('old')
    unrelated=tmp_path/'my-documents';unrelated.mkdir();(unrelated/'keep').write_text('important')
    clean_abandoned_work(tmp_path)
    assert not stale.exists()
    assert (unrelated/'keep').exists()

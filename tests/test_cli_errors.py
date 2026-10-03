import pytest
from nordrag import cli
from nordrag.util import write_json, read_json
from test_build import Engines


@pytest.fixture
def builder_cli(monkeypatch, tmp_path):
    engine = Engines()
    engine.close = lambda: None
    monkeypatch.setattr(cli, 'configure_logging', lambda mode: None)
    monkeypatch.setattr(cli, 'data_home', lambda: tmp_path / 'home')
    monkeypatch.setattr(cli, 'load_config', lambda path: {})
    monkeypatch.setattr(cli, 'Engines', lambda *args, **kwargs: engine)
    return engine


def run_build(deck, tmp_path):
    return cli.main(['build', '--input', str(deck.parent), '--name', '诊断测试',
                     '--output', str(tmp_path / 'result.ragkb'), '--yes'])


def test_document_failure_prints_reason_stage_and_report(deck, tmp_path, builder_cli, capsys):
    builder_cli.convert = lambda *args: (_ for _ in ()).throw(RuntimeError('测试转换组件无法加载字体'))
    assert run_build(deck, tmp_path) == 1
    captured = capsys.readouterr()
    assert '测试转换组件无法加载字体' in captured.err
    assert deck.name in captured.err
    assert 'PDF' in captured.err
    assert str(tmp_path / 'result.report.json') in captured.err
    report = read_json(tmp_path / 'result.report.json')
    assert report['failed'][0]['stage'] == 'convert'
    assert report['failed'][0]['error_type'] == 'RuntimeError'


def test_empty_timeout_has_actionable_message(deck, tmp_path, builder_cli, capsys):
    import httpx
    builder_cli.organize = lambda *args: (_ for _ in ()).throw(httpx.ReadTimeout(''))
    assert run_build(deck, tmp_path) == 1
    error = capsys.readouterr().err
    assert 'ReadTimeout' in error and '超时' in error and '总结' in error


def test_global_embedding_failure_identifies_stage(deck, tmp_path, builder_cli, capsys):
    builder_cli.embed = lambda *args: (_ for _ in ()).throw(RuntimeError('嵌入模型测试错误'))
    assert run_build(deck, tmp_path) == 1
    error = capsys.readouterr().err
    assert '嵌入模型测试错误' in error and '向量' in error
    assert str(tmp_path / 'result.report.json') in error


def test_existing_output_does_not_report_stale_failure(deck, tmp_path, builder_cli, capsys):
    (tmp_path / 'result.ragkb').write_bytes(b'existing')
    write_json(tmp_path / 'result.report.json', {'failed':[{'path':'old.pptx','error':'旧错误不应显示'}]})
    assert run_build(deck, tmp_path) == 1
    error = capsys.readouterr().err
    assert '输出已存在' in error
    assert '旧错误不应显示' not in error
    assert 'result.report.json' not in error


def test_initialization_failure_is_printed(deck, tmp_path, builder_cli, monkeypatch, capsys):
    monkeypatch.setattr(cli, 'Engines', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('缺少 OCR 运行组件')))
    assert run_build(deck, tmp_path) == 1
    assert '缺少 OCR 运行组件' in capsys.readouterr().err


def test_report_write_failure_does_not_hide_document_error(deck, tmp_path, builder_cli, monkeypatch, capsys):
    import nordrag.builder as builder
    original_write = builder.write_json
    def write(path, value):
        if isinstance(value, dict) and value.get('status') == 'failed':
            raise PermissionError('报告目录不可写')
        original_write(path, value)
    monkeypatch.setattr(builder, 'write_json', write)
    builder_cli.convert = lambda *args: (_ for _ in ()).throw(RuntimeError('原始转换错误'))
    assert run_build(deck, tmp_path) == 1
    error = capsys.readouterr().err
    assert '原始转换错误' in error
    assert '报告未能保存' in error and '报告目录不可写' in error
    assert '详细报告：' not in error


def test_corrupt_input_is_named_in_final_summary(tmp_path, builder_cli, capsys):
    source = tmp_path / '损坏文件.pptx'
    source.write_bytes(b'not a presentation')
    assert run_build(source, tmp_path) == 1
    error = capsys.readouterr().err
    assert '损坏文件.pptx' in error and '扫描 PPTX' in error
    assert '详细报告：' in error


def test_user_interrupt_has_reason_and_cancelled_report(deck, tmp_path, builder_cli, capsys):
    builder_cli.organize = lambda *args: (_ for _ in ()).throw(KeyboardInterrupt())
    assert run_build(deck, tmp_path) == 1
    assert '用户中断' in capsys.readouterr().err
    assert read_json(tmp_path / 'result.report.json')['status'] == 'cancelled'


def test_cleanup_error_does_not_replace_original_failure(deck, tmp_path, builder_cli, capsys):
    builder_cli.embed = lambda *args: (_ for _ in ()).throw(RuntimeError('原始向量错误'))
    builder_cli.close = lambda: (_ for _ in ()).throw(OSError('组件清理错误'))
    assert run_build(deck, tmp_path) == 1
    error = capsys.readouterr().err
    assert '原始向量错误' in error
    assert str(tmp_path / 'result.report.json') in error
    assert '组件清理错误' in error


def test_partial_success_exits_zero_and_lists_skipped_files(deck, tmp_path, builder_cli, capsys):
    (tmp_path / 'broken.pptx').write_bytes(b'broken')
    assert run_build(deck, tmp_path) == 0
    captured = capsys.readouterr()
    assert '构建完成，部分文件已跳过' in captured.out
    assert '成功 1 个文档，跳过 1 个失败文件' in captured.out
    assert str(tmp_path / 'result.report.json') in captured.out
    assert 'broken.pptx' in captured.err and '扫描 PPTX' in captured.err


def test_partial_report_save_failure_keeps_document_reason(deck, tmp_path, builder_cli, monkeypatch, capsys):
    import nordrag.builder as builder
    original = builder.write_json
    (tmp_path / 'broken.pptx').write_bytes(b'broken')
    def write(path, value):
        if path.name == 'result.report.json' and value.get('status') != 'building':
            raise PermissionError('报告写入失败')
        original(path, value)
    monkeypatch.setattr(builder, 'write_json', write)
    assert run_build(deck, tmp_path) == 1
    error = capsys.readouterr().err
    assert 'broken.pptx' in error and '报告写入失败' in error
    assert '报告未能保存' in error

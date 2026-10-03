import argparse
import json
import sys
import threading
from pathlib import Path
from .builder import build, BuildError
from .diagnostics import describe_error, STAGES
from .config import load_config, preflight
from .engines import Engines
from .parsing import scan
from .package import validate
from .util import data_home, read_json
from .operations import OperationLock
from .logging_utils import configure_logging, logger


def print_failure(failure):
    stage = STAGES.get(failure.get('stage'), failure.get('stage', '处理文档'))
    print(f"  文件：{failure['path']}\n  阶段：{stage}\n  原因：{failure['error']}", file=sys.stderr, flush=True)


def print_progress(event):
    if event['stage'] == 'retry':
        print(f"[自动恢复] {event['document']}：{event['reason']}；重启本地模型，缩小处理批次后重试（第 {event['attempt']}/{event['attempts']} 次）。", flush=True)
    elif event['stage'] == 'failed':
        print('文档处理失败：', file=sys.stderr, flush=True)
        print_failure(event['failure'])
    else:
        stage = STAGES.get(event['stage'], {'parsed': '文档处理完成', 'complete': '知识库构建完成'}.get(event['stage'], event['stage']))
        detail = event.get('document', event.get('output', ''))
        if 'completed' in event:
            detail = f"{detail} {event['completed']} / {event['total']}"
        print(f'[{stage}] {detail}', flush=True)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Nord 离线 PPTX 知识库构建工具")
    parser.add_argument("--config", type=Path)
    sub = parser.add_subparsers(dest="command")
    b = sub.add_parser("build")
    b.add_argument("--input", type=Path, required=True)
    b.add_argument("--name", required=True)
    b.add_argument("--output", type=Path, required=True)
    b.add_argument("--exclude", action="append", default=[], help="相对输入目录的文件路径，可重复")
    b.add_argument("--yes", action="store_true")
    s = sub.add_parser("scan")
    s.add_argument("input", type=Path)
    sub.add_parser("doctor")
    args = parser.parse_args(argv)
    interactive = args.command is None
    try:
        configure_logging('builder')
        if interactive:
            args.command = "build"
            args.input = Path(input("PPTX 目录：").strip().strip('"'))
            args.name = input("知识库名称：").strip() or "部门知识库"
            args.output = Path(input("输出 .ragkb 路径：").strip().strip('"'))
            args.exclude, args.yes = [], False
        if args.command == "scan":
            print(json.dumps(scan(args.input), ensure_ascii=False, indent=2))
            return 0
        cfg = load_config(args.config)
        if args.command == "doctor":
            errors = preflight(cfg, build=True)
            print("\n".join(errors) if errors else "运行组件与模型校验通过")
            return 1 if errors else 0
        inventory = scan(args.input, args.exclude)
        print(json.dumps(inventory, ensure_ascii=False, indent=2))
        print(f"文件数 {len(inventory['documents'])}，总页数 {sum(d['pages'] for d in inventory['documents'])}")
        if not args.yes and input("确认开始构建？输入 y：").strip().lower() != "y":
            return 0
        operation = OperationLock(data_home())
        if not operation.acquire():
            raise RuntimeError("已有构建或生成任务，请等待完成")
        engines = None
        try:
            engines = Engines(cfg, build=True)
            result = build(args.input, args.name, args.output, data_home() / "cache", engines, threading.Event(), args.exclude, print_progress)
            logger.info('build_completed documents=%s pages=%s', len(result['included']), result['total_pages'])
            print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            active_error = sys.exc_info()[1]
            cleanup_errors = []
            cleanups = ([engines.close] if engines else []) + [operation.release]
            for cleanup in cleanups:
                try:
                    cleanup()
                except Exception as cleanup_error:
                    cleanup_errors.append(cleanup_error)
                    print(f'清理资源时发生错误：{describe_error(cleanup_error)}', file=sys.stderr, flush=True)
            if cleanup_errors and active_error is None:
                raise cleanup_errors[0]
        return 0
    except (Exception, KeyboardInterrupt) as e:
        logger.warning('build_failed exception_type=%s', type(e).__name__)
        print(f"构建未完成：{describe_error(e)}", file=sys.stderr, flush=True)
        if isinstance(e, BuildError) and e.report:
            report = e.report
            if report.get('failed'):
                print(f"失败文件共 {len(report['failed'])} 个：", file=sys.stderr)
                for failure in report['failed']:
                    print_failure(failure)
            else:
                print(f"失败阶段：{STAGES.get(report.get('stage'), report.get('stage', '未知'))}\n原因：{report['error']}", file=sys.stderr)
            if e.report_path:
                print(f"详细报告：{e.report_path}", file=sys.stderr, flush=True)
            elif report.get('report_error'):
                print(f"报告未能保存：{report['report_error']}", file=sys.stderr, flush=True)
        if isinstance(e, FileExistsError):
            print('请换一个新的输出文件名，例如：知识库_v2.ragkb。已有文件不会被覆盖。', file=sys.stderr)
        return 1
    finally:
        if interactive:
            try:
                input("按回车关闭窗口…")
            except (EOFError, KeyboardInterrupt):
                pass


if __name__ == "__main__":
    raise SystemExit(main())

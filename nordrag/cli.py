import argparse
import json
import sys
import threading
from pathlib import Path
from .builder import build
from .config import load_config, preflight
from .engines import Engines
from .parsing import scan
from .package import validate
from .util import data_home, read_json
from .operations import OperationLock
from .logging_utils import configure_logging, logger


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
            result = build(args.input, args.name, args.output, data_home() / "cache", engines, threading.Event(), args.exclude, lambda e: print(json.dumps(e, ensure_ascii=False), flush=True))
            logger.info('build_completed documents=%s pages=%s', len(result['included']), result['total_pages'])
            print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            if engines:
                engines.close()
            operation.release()
        return 0
    except (Exception, KeyboardInterrupt) as e:
        logger.warning('build_failed exception_type=%s', type(e).__name__)
        print(f"构建未完成：{e}", file=sys.stderr)
        return 1
    finally:
        if interactive:
            input("按回车关闭窗口…")


if __name__ == "__main__":
    raise SystemExit(main())

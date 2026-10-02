import argparse
import secrets
import shutil
import sys
import threading
import webbrowser
from pathlib import Path
import uvicorn
from .api import create_app
from .config import load_config, app_root
from .engines import Engines, free_port
from .package import open_package
from .util import data_home, read_json, write_json
from .operations import OperationLock
from .workspace import clean_abandoned_work
from .logging_utils import configure_logging, logger


def main(argv=None):
    parser = argparse.ArgumentParser(description="Nord browser chat")
    parser.add_argument("--knowledge", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--choose", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    home = data_home()
    configure_logging('chat')
    lifetime = OperationLock(home, "application.lock")
    if not lifetime.acquire():
        print("聊天程序已在运行，请使用现有窗口。")
        return 1
    settings = home / "settings.json"
    engines = None
    root = None
    try:
        clean_abandoned_work(home / "work")
        path = args.knowledge
        if not path and settings.exists() and not args.choose:
            path = Path(read_json(settings).get("knowledge", ""))
        if not path or not path.is_file():
            from tkinter import Tk, filedialog
            window = Tk()
            window.withdraw()
            selected = filedialog.askopenfilename(title="选择知识库文件", filetypes=[("Nord 知识库", "*.ragkb")])
            window.destroy()
            if not selected:
                return 0
            path = Path(selected)
        cfg = load_config(args.config)
        print('正在校验离线运行组件和知识库，请稍候…', flush=True)
        engines = Engines(cfg)
        root, manifest = open_package(path, home / "work", engines.embedding_id)
        write_json(settings, {"knowledge": str(path.resolve())})
        static = app_root() / "frontend" / "dist"
        if not static.is_dir():
            raise RuntimeError("缺少前端构建，请先构建 frontend")
        token = secrets.token_urlsafe(32)
        app = create_app(root, manifest, engines, home, token, static)
        port = free_port()
        url = f"http://127.0.0.1:{port}/#token={token}"
        print(f"Nord 已启动：{url}\n保留此窗口；按 Ctrl+C 退出并停止模型。", flush=True)
        if not args.no_browser:
            threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        uvicorn.run(app, host="127.0.0.1", port=port, access_log=False)
        return 0
    except Exception as e:
        logger.warning('startup_failed exception_type=%s', type(e).__name__)
        print(f"启动失败：{e}")
        if getattr(sys, "frozen", False):
            input("按回车关闭…")
        return 1
    finally:
        try:
            if engines:
                engines.close()
            if root and root.exists():
                shutil.rmtree(root)
        finally:
            logger.info('application_stopped')
            lifetime.release()


if __name__ == "__main__":
    raise SystemExit(main())

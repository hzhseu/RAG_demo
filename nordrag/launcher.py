import argparse
import secrets
import sys
import threading
import webbrowser
from pathlib import Path
import uvicorn
from .api import create_app
from .config import load_config, app_root
from .engines import Engines, free_port
from .util import data_home
from .operations import OperationLock
from .workspace import clean_abandoned_work
from .logging_utils import configure_logging, logger


def main(argv=None):
    parser = argparse.ArgumentParser(description="RadioMind browser chat")
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
    engines = None
    manager = None
    try:
        clean_abandoned_work(home / "work")
        cfg = load_config(args.config)
        print('正在校验离线运行组件，请稍候…', flush=True)
        engines = Engines(cfg, allow_unavailable_chat=True)
        static = app_root() / "frontend" / "dist"
        if not static.is_dir():
            raise RuntimeError("缺少前端构建，请先构建 frontend")
        token = secrets.token_urlsafe(32)
        app = create_app(None, None, engines, home, token, static)
        if app.state.models: app.state.models.restore()
        manager = app.state.knowledge
        manager.restore(args.knowledge, choose=args.choose)
        port = free_port()
        url = f"http://127.0.0.1:{port}/#token={token}"
        print(f"RadioMind 已启动：{url}\n保留此窗口；按 Ctrl+C 退出并停止模型。", flush=True)
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
            if manager:
                manager.close()
        finally:
            logger.info('application_stopped')
            lifetime.release()


if __name__ == "__main__":
    raise SystemExit(main())

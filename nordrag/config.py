import json
import hashlib
import sys
from pathlib import Path
from .util import read_json, digest


def app_root():
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent


def load_config(path=None):
    path = Path(path) if path else app_root() / "runtime.json"
    if not path.exists():
        raise FileNotFoundError(f"缺少运行配置 {path}。请参阅 README 中的离线组件准备步骤。")
    cfg = read_json(path)
    cfg["root"] = str(path.resolve().parent)
    return cfg


def asset(cfg, key):
    value = cfg[key]
    p = Path(value)
    return p if p.is_absolute() else Path(cfg["root"]) / p


def preflight(cfg, build=False, check_chat=True):
    keys = ["llama_server", "embedding_model"] + (["chat_model"] if check_chat else [])
    if build:
        keys += ["soffice", "ocr_python", "ocr_detection", "ocr_recognition"]
    errors = []
    for key in keys:
        if key not in cfg or not asset(cfg, key).exists():
            errors.append(f"缺少 {key}: {cfg.get(key, '(未配置)')}")
    if not errors:
        for key in (["chat_model"] if check_chat else []) + ["embedding_model"]:
            expected = cfg.get(key + "_sha256")
            if not expected:
                errors.append(f"未固定 {key} SHA256，请运行 scripts/freeze_runtime.py")
            elif digest(asset(cfg, key)) != expected:
                errors.append(f"{key} 校验失败")
    runtime = Path(cfg["root"]) / "runtime"
    lock = runtime / "runtime-lock.json"
    if not lock.is_file() or not cfg.get("runtime_digest"):
        errors.append("缺少运行组件锁定清单，请运行 scripts/freeze_runtime.py")
    else:
        try:
            files = read_json(lock)
            if hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest() != cfg["runtime_digest"]:
                errors.append("运行组件清单摘要不匹配")
            else:
                for name, expected in files.items():
                    # Reranking is optional; its weights are checked before use.
                    if cfg.get('reranker_model') and (runtime / name).resolve() == asset(cfg, 'reranker_model').resolve():
                        continue
                    # Answer weights are optional at startup and validated by the
                    # model registry before use; embedding remains mandatory.
                    if not check_chat and name.startswith('models/') and Path(name).name != asset(cfg,'embedding_model').name:
                        continue
                    path = (runtime / name).resolve()
                    if not path.is_relative_to(runtime.resolve()) or not path.is_file() or digest(path) != expected:
                        errors.append(f"运行组件校验失败：{name}")
                        if len(errors) >= 10:
                            break
        except (OSError, ValueError, TypeError):
            errors.append("运行组件清单无效")
    return errors

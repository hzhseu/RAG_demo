import hashlib
import json
import os
from pathlib import Path


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".writing")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def data_home() -> Path:
    root = Path(os.environ.get("NORDRAG_DATA", Path(os.environ.get("LOCALAPPDATA", Path.home())) / "NordRAG"))
    root.mkdir(parents=True, exist_ok=True)
    return root

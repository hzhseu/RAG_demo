"""Self-contained, checksummed packages. Never trust archive member paths."""
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from .util import digest, read_json, write_json


class PackageError(ValueError):
    pass


def content_version(manifest):
    data = {k: v for k, v in manifest.items() if k not in ("version", "built_at")}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def seal(root: Path, output: Path, metadata: dict):
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"输出已存在：{output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    files = {p.relative_to(root).as_posix(): digest(p) for p in sorted(root.rglob("*")) if p.is_file() and p.name != "manifest.json"}
    manifest = {**metadata, "format": 1, "built_at": datetime.now(timezone.utc).isoformat(), "files": files}
    manifest["version"] = content_version(manifest)
    fd, tmp = tempfile.mkstemp(dir=output.parent, suffix=".partial")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
            for name in files:
                z.write(root / name, name)
        validate(Path(tmp), metadata["embedding"])
        # Windows rename is atomic and refuses overwrite, including on exFAT/FAT.
        if os.name == "nt":
            os.rename(tmp, output)
        else:
            os.link(tmp, output)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return manifest


def validate(package: Path, embedding: str):
    try:
        with zipfile.ZipFile(package) as z:
            names = z.namelist()
            if len(names) != len(set(n.casefold() for n in names)) or len(names) > 100000:
                raise PackageError("知识库包含重复或过多条目")
            total = 0
            for i in z.infolist():
                p = PurePosixPath(i.filename)
                if p.as_posix() != i.filename or p.is_absolute() or ".." in p.parts or "\\" in i.filename or ":" in i.filename or not p.parts or i.is_dir():
                    raise PackageError("知识库包含非法路径")
                reserved = {"CON", "PRN", "AUX", "NUL"} | {f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10)}
                if any(x.split('.')[0].upper() in reserved for x in p.parts):
                    raise PackageError("知识库包含 Windows 保留路径")
                if any(x.endswith((".", " ")) for x in p.parts):
                    raise PackageError("知识库包含非法路径")
                total += i.file_size
                if total > 20 * 1024**3:
                    raise PackageError("知识库解包体积超过 20GB")
            m = json.loads(z.read("manifest.json"))
            if m.get("format") != 1:
                raise PackageError("知识库格式版本不兼容")
            if m.get("embedding") != embedding:
                raise PackageError(f"嵌入模型不兼容：知识库需要 {m.get('embedding')}；当前为 {embedding}。请使用匹配模型或重新构建。")
            if m.get("version") != content_version(m):
                raise PackageError("清单校验失败")
            if set(names) != set(m["files"]) | {"manifest.json"}:
                raise PackageError("知识库文件清单不完整")
            for name, expected in m["files"].items():
                h = hashlib.sha256()
                with z.open(name) as f:
                    for b in iter(lambda: f.read(1024 * 1024), b""):
                        h.update(b)
                if h.hexdigest() != expected:
                    raise PackageError(f"文件校验失败：{name}")
            return m
    except (KeyError, TypeError, zipfile.BadZipFile, json.JSONDecodeError) as e:
        raise PackageError("知识库损坏或清单无效") from e


def open_package(package: Path, work_parent: Path, embedding: str):
    m = validate(package, embedding)
    work_parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=m["version"] + "-", dir=work_parent))
    try:
        with zipfile.ZipFile(package) as z:
            z.extractall(root)
    except BaseException:
        shutil.rmtree(root)
        raise
    return root, m


def export_package(root: Path, output: Path, documents):
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        staging = Path(tmp) / "content"
        shutil.copytree(root, staging)
        write_json(staging / "documents.json", documents)
        m = read_json(root / "manifest.json")
        return seal(staging, output, {k: v for k, v in m.items() if k not in ("files", "version", "built_at", "format")})

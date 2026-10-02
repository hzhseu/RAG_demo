"""Development-time downloads. Runtime applications never call this script."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import zipfile
import httpx

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime"


def download(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        print(f"Already present: {path.name}", flush=True)
        return path
    temp = path.with_suffix(path.suffix + ".partial")
    print(f"Downloading: {path.name}", flush=True)
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as response:
        response.raise_for_status()
        with temp.open("wb") as f:
            for chunk in response.iter_bytes(1024 * 1024):
                f.write(chunk)
    temp.replace(path)
    print(f"Ready: {path.name} ({path.stat().st_size//1024//1024} MB)", flush=True)
    return path


def model(repo, filename):
    metadata = httpx.get(f"https://huggingface.co/api/models/{repo}", timeout=60, follow_redirects=True).json()
    revision = metadata["sha"]
    url = f"https://huggingface.co/{repo}/resolve/{revision}/{filename}"
    path = download(url, RUNTIME / "models" / filename)
    return {"name": filename, "source": url, "revision": revision, "sha256": sha(path), "license": "Apache-2.0 (see model card)"}


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024*1024), b""):
            h.update(b)
    return h.hexdigest()


def main():
    RUNTIME.mkdir(exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(model, "unsloth/Qwen3-4B-Instruct-2507-GGUF", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"), pool.submit(model, "Qwen/Qwen3-Embedding-0.6B-GGUF", "Qwen3-Embedding-0.6B-Q8_0.gguf")]
        url = "https://github.com/ggml-org/llama.cpp/releases/download/b11326/llama-b11326-bin-win-cpu-x64.zip"
        llama = pool.submit(download, url, RUNTIME / "downloads" / "llama-b11326.zip")
        for name in ("PP-OCRv5_mobile_det", "PP-OCRv5_mobile_rec"):
            jobs.append(pool.submit(ocr_model, name))
        records = [j.result() for j in jobs]
        archive = llama.result()
        with zipfile.ZipFile(archive) as z:
            z.extractall(RUNTIME / "llama")
        records.append({"name": "llama.cpp b11326", "source": url, "sha256": sha(archive), "license": "MIT"})
    (RUNTIME / "sources.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def ocr_model(name):
    url = f"https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/{name}_infer.tar"
    path = download(url, RUNTIME / "downloads" / f"{name}.tar")
    target = RUNTIME / "ocr-models"
    target.mkdir(exist_ok=True)
    with tarfile.open(path) as t:
        t.extractall(target, filter="data")
    return {"name": name, "source": url, "sha256": sha(path), "license": "Apache-2.0"}


if __name__ == "__main__":
    main()

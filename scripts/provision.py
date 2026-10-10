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


def model(repo, filename, revision, expected):
    url = f"https://huggingface.co/{repo}/resolve/{revision}/{filename}"
    path = download(url, RUNTIME / "models" / filename)
    if sha(path) != expected:raise ValueError(f'Model SHA256 mismatch: {filename}')
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
        jobs = [pool.submit(model, "unsloth/Qwen3-4B-Instruct-2507-GGUF", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf", "a06e946bb6b655725eafa393f4a9745d460374c9", "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"), pool.submit(model, "Qwen/Qwen3-Embedding-0.6B-GGUF", "Qwen3-Embedding-0.6B-Q8_0.gguf", "370f27d7550e0def9b39c1f16d3fbaa13aa67728", "06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439"), pool.submit(model,"unsloth/Qwen3.5-4B-GGUF","Qwen3.5-4B-Q4_K_M.gguf","e87f176479d0855a907a41277aca2f8ee7a09523","00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4")]
        url = "https://github.com/ggml-org/llama.cpp/releases/download/b11326/llama-b11326-bin-win-cpu-x64.zip"
        llama = pool.submit(download, url, RUNTIME / "downloads" / "llama-b11326.zip")
        for name in ("PP-OCRv5_mobile_det", "PP-OCRv5_mobile_rec"):
            jobs.append(pool.submit(ocr_model, name))
        jobs.append(pool.submit(model, "ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF", "qwen3-reranker-0.6b-q8_0.gguf", "a02f48bb4f057028298c21fa033da2b30d7742d5", "22c9979ce4fbcdc5acdc310c6641c32797eff1aa980b8f7a2db8a8ea23429a48"))
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

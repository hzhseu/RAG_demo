"""Collect publisher notices into the offline runtime before freezing hashes."""
import json
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parent.parent
folder=ROOT/'runtime/licenses';folder.mkdir(exist_ok=True)
sources={
 'llama.cpp-LICENSE.txt':'https://raw.githubusercontent.com/ggml-org/llama.cpp/b11326/LICENSE',
 'Qwen3-4B-Instruct-2507-LICENSE.txt':'https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/raw/main/LICENSE',
 'Apache-2.0.txt':'https://www.apache.org/licenses/LICENSE-2.0.txt',
 'Qwen3-Embedding-model-card.md':'https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF/raw/370f27d7550e0def9b39c1f16d3fbaa13aa67728/README.md',
 'Qwen3-Reranker-GGUF-model-card.md':'https://huggingface.co/ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF/raw/a02f48bb4f057028298c21fa033da2b30d7742d5/README.md',
 'Qwen3-4B-GGUF-model-card.md':'https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/raw/main/README.md',
 'PaddleOCR-LICENSE.txt':'https://raw.githubusercontent.com/PaddlePaddle/PaddleOCR/v3.5.0/LICENSE',
 'PaddlePaddle-LICENSE.txt':'https://raw.githubusercontent.com/PaddlePaddle/Paddle/v3.3.1/LICENSE',
}
for name,url in sources.items():
    r=httpx.get(url,follow_redirects=True,timeout=60);r.raise_for_status();(folder/name).write_bytes(r.content)
frontend=ROOT/'frontend/node_modules'
for package in ('react','react-dom','pdfjs-dist'):
    p=frontend/package/'LICENSE'
    if p.exists():(folder/(package+'-LICENSE.txt')).write_bytes(p.read_bytes())
(folder/'SOURCES.json').write_text(json.dumps(sources,indent=2),encoding='utf-8')
print('Publisher licenses collected')

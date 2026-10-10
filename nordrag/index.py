import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
import numpy as np


def terms(text):
    en = re.findall(r"[a-z0-9]+", text.lower())
    cn = re.findall(r"[\u3400-\u9fff]+", text)
    return en + [s[i:i+2] for s in cn for i in range(max(1, len(s)-1))]


def create_index(root: Path, chunks, vectors):
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.ndim != 2 or len(matrix) != len(chunks) or not np.isfinite(matrix).all():
        raise ValueError("无效嵌入矩阵")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("嵌入向量不能为空")
    np.save(root / "vectors.npy", matrix / norms, allow_pickle=False)
    with closing(sqlite3.connect(root / "index.sqlite")) as db:
        db.execute("CREATE TABLE chunks (idx INTEGER PRIMARY KEY, data TEXT NOT NULL)")
        db.execute("CREATE VIRTUAL TABLE search USING fts5(tokens)")
        for i, c in enumerate(chunks):
            db.execute("INSERT INTO chunks VALUES (?, ?)", (i, json.dumps(c, ensure_ascii=False)))
            db.execute("INSERT INTO search(rowid,tokens) VALUES (?,?)", (i + 1, " ".join(terms(c["text"]))))
        db.commit()


def all_chunks(root):
    with closing(sqlite3.connect(f"{(root / 'index.sqlite').as_uri()}?mode=ro", uri=True)) as db:
        return [json.loads(row[0]) for row in db.execute("SELECT data FROM chunks ORDER BY idx")]


def retrieve(root: Path, query, vector, limit=8):
    matrix = np.load(root / "vectors.npy", allow_pickle=False)
    v = np.asarray(vector, dtype=np.float32)
    if v.ndim != 1 or matrix.shape[1] != len(v) or not np.isfinite(v).all() or np.linalg.norm(v) == 0:
        raise ValueError("查询嵌入与索引维度不兼容")
    cosine = matrix @ (v / np.linalg.norm(v))
    semantic = np.argsort(-cosine)[:30].tolist()
    tokens = list(dict.fromkeys(terms(query)))[:60]
    with closing(sqlite3.connect(f"{(root / 'index.sqlite').as_uri()}?mode=ro", uri=True)) as db:
        lexical = []
        if tokens:
            expression = " OR ".join('"' + t + '"' for t in tokens)
            lexical = [r[0] - 1 for r in db.execute("SELECT rowid FROM search WHERE search MATCH ? ORDER BY rank LIMIT 30", (expression,))]
        scores = {}
        for ranking in (semantic, lexical):
            for rank, idx in enumerate(ranking):
                scores[idx] = scores.get(idx, 0) + 1 / (60 + rank + 1)
        results = []
        for idx in sorted(scores, key=scores.get, reverse=True)[:limit]:
            c = json.loads(db.execute("SELECT data FROM chunks WHERE idx=?", (idx,)).fetchone()[0])
            results.append({**c, "score": scores[idx], "similarity": float(cosine[idx])})
        return results


def deduplicate_candidates(candidates, limit=30):
    """Keep RRF order and distinct provenance, dates, units and table rows."""
    seen, result = set(), []
    for chunk in candidates:
        key = (chunk['doc_id'], chunk['page'], chunk['kind'], ' '.join(chunk['text'].split()))
        if key not in seen:
            seen.add(key)
            result.append(chunk)
            if len(result) >= limit:
                break
    return result


def retrieve_candidates(root: Path, query, vector, limit=30):
    return deduplicate_candidates(retrieve(root, query, vector, limit=60), limit)

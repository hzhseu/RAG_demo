"""PPTX extraction preserves slide coordinates; OCR is an injected external boundary."""
from pathlib import Path
from io import BytesIO
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from .util import digest

PARSER_VERSION = "2"
CHUNK_MAX_CHARS = 1400


def scan(directory: Path, excluded=()):
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise ValueError("输入目录不存在")
    result = {"documents": [], "duplicates": [], "failed": [], "excluded": []}
    seen = {}
    for path in sorted(directory.rglob("*")):
        if path.suffix.lower() != ".pptx" or path.name.startswith("~$") or not path.is_file():
            continue
        rel = path.relative_to(directory).as_posix()
        if rel in excluded:
            result["excluded"].append(rel)
            continue
        try:
            sha = digest(path)
            if sha in seen:
                result["duplicates"].append({"path": rel, "same_as": seen[sha]})
                continue
            pages = len(Presentation(path).slides)
            if not pages:
                raise ValueError("没有幻灯片")
            seen[sha] = rel
            result["documents"].append({"id": sha, "name": path.name, "relative_path": rel, "path": str(path), "sha256": sha, "pages": pages})
        except Exception as e:
            result["failed"].append({"path": rel, "error": str(e)})
    return result


def parse_pptx(path: Path, ocr=None, image_dir: Path | None = None):
    prs = Presentation(path)
    pages = []
    for number, slide in enumerate(prs.slides, 1):
        blocks = []

        def walk(shapes):
            for shape in shapes:
                if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                    walk(shape.shapes)
                elif shape.has_table:
                    rows = [["" if c.is_spanned else c.text.strip() for c in row.cells] for row in shape.table.rows]
                    blocks.append({"kind": "table", "rows": rows, "text": "\n".join(" | ".join(r) for r in rows)})
                elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    blob = shape.image.blob
                    image_name = f"p{number}-{shape.shape_id}.{shape.image.ext}"
                    if image_dir:
                        image_dir.mkdir(parents=True, exist_ok=True)
                        (image_dir / image_name).write_bytes(blob)
                    if ocr is None:
                        raise ValueError(f"第 {number} 页含图片，需要配置离线 OCR")
                    text = ocr(blob)
                    blocks.append({"kind": "ocr", "text": text, "image": image_name})
                elif shape.has_chart:
                    chart = shape.chart
                    text = []
                    if chart.has_title and chart.chart_title.has_text_frame:
                        text.append(chart.chart_title.text_frame.text)
                    try:
                        text.append(" | ".join(str(x.label) for x in chart.plots[0].categories))
                        for series in chart.series:
                            text.append(str(series.name) + " | " + " | ".join(map(str, series.values)))
                    except (ValueError, AttributeError):
                        text.append("图表结构未完全提取，请核对原页")
                    blocks.append({"kind": "chart", "text": "\n".join(text)})
                elif shape.has_text_frame and shape.text.strip():
                    blocks.append({"kind": "text", "text": shape.text.strip()})

        walk(slide.shapes)
        if slide.has_notes_slide:
            frame = slide.notes_slide.notes_text_frame
            if frame and frame.text.strip():
                blocks.append({"kind": "notes", "text": frame.text.strip()})
        pages.append({"page": number, "blocks": blocks})
    return pages


def chunk_pages(doc_id, pages, max_chars=CHUNK_MAX_CHARS):
    if max_chars < 64:
        raise ValueError("chunk size too small")
    chunks = []
    for page in pages:
        non_tables = [b for b in page['blocks'] if b['kind'] != 'table']
        context = '\n'.join(b['text'] for b in non_tables if b['kind'] == 'text')
        combined = '\n'.join(('[备注 / notes] ' if b['kind'] == 'notes' else '') + b['text'] for b in non_tables)
        combined_kind = 'ocr' if any(b['kind'] == 'ocr' for b in non_tables) else 'text'
        blocks = ([{'kind':combined_kind,'text':combined}] if combined.strip() else []) + [b for b in page['blocks'] if b['kind'] == 'table']
        for block in blocks:
            texts = []
            if block["kind"] == "table" and block.get("rows"):
                header = (context + '\n' if context else '') + " | ".join(block["rows"][0])
                # One complete row per chunk: never detach values from headers/units.
                texts = [header + "\n" + " | ".join(row) for row in block["rows"][1:]] or [header]
            else:
                value = block["text"].strip()
                step = max_chars - 100 if max_chars > 200 else max_chars
                texts = [value[i:i + max_chars] for i in range(0, len(value), step)]
            for text in texts:
                if not text.strip():
                    continue
                chunks.append({"id": f"{doc_id}:{page['page']}:{len(chunks)}", "doc_id": doc_id, "page": page["page"], "kind": block["kind"], "text": text, "image": block.get("image")})
    return chunks

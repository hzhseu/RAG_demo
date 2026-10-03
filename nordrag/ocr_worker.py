"""Executed by the separately bundled PaddleOCR Python runtime, never downloads models."""
import json
import os
import sys
from pathlib import Path
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["HF_HUB_OFFLINE"] = "1"


def main():
    image, output, detection, recognition = sys.argv[1:]
    output = Path(output)
    stage = 'initialize'
    output.write_text(json.dumps({'stage': stage}), encoding='utf-8')
    try:
        from paddleocr import PaddleOCR
        from PIL import Image
        import numpy as np
        for folder in (detection, recognition):
            if not Path(folder).is_dir():
                raise RuntimeError("Local OCR model missing")
        ocr = PaddleOCR(text_detection_model_name="PP-OCRv5_mobile_det", text_detection_model_dir=detection, text_recognition_model_name="PP-OCRv5_mobile_rec", text_recognition_model_dir=recognition, use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False, device="cpu", cpu_threads=2, enable_mkldnn=False)
        stage = 'document'
        output.write_text(json.dumps({'stage': stage}), encoding='utf-8')
        with Image.open(image) as picture:
            result = ocr.predict(np.array(picture.convert("RGB")))
        lines = []
        for page in result:
            lines.extend(page["rec_texts"])
    except Exception as error:
        if isinstance(error, MemoryError) or isinstance(error, OSError) and error.errno is not None:
            stage = 'resource'
        output.write_text(json.dumps({'stage': stage, 'error_type': type(error).__name__,
                                      'error': str(error) or 'OCR 组件未提供详细错误'}, ensure_ascii=False), encoding='utf-8')
        return 1
    output.write_text(json.dumps({"text": "\n".join(lines)}, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

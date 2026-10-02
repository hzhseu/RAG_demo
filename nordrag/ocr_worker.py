"""Executed by the separately bundled PaddleOCR Python runtime, never downloads models."""
import json
import os
import sys
from pathlib import Path
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["HF_HUB_OFFLINE"] = "1"


def main():
    from paddleocr import PaddleOCR
    from PIL import Image
    import numpy as np
    image, output, detection, recognition = sys.argv[1:]
    for folder in (detection, recognition):
        if not Path(folder).is_dir():
            raise RuntimeError("Local OCR model missing")
    ocr = PaddleOCR(text_detection_model_name="PP-OCRv5_mobile_det", text_detection_model_dir=detection, text_recognition_model_name="PP-OCRv5_mobile_rec", text_recognition_model_dir=recognition, use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False, device="cpu", cpu_threads=2, enable_mkldnn=False)
    result = ocr.predict(np.array(Image.open(image).convert("RGB")))
    lines = []
    for page in result:
        lines.extend(page["rec_texts"])
    Path(output).write_text(json.dumps({"text": "\n".join(lines)}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

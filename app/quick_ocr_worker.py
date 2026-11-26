"""Isolated local OCR worker. Installed engines and weights are never downloaded here."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import sys
import warnings
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

PINS = {"rapidocr": "3.10.0", "onnxruntime": "1.24.3", "Pillow": "13.0.0", "opencv-python-headless": "5.1.0.95"}
MODELS = {
    "Det": ("PP-OCRv6_det_small.onnx", "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f"),
    "Rec": ("PP-OCRv6_rec_small.onnx", "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884"),
    "Cls": ("ch_ppocr_mobile_v2.0_cls_mobile.onnx", "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c"),
}

MAX_BYTES = 40 * 1024 * 1024
MAX_PIXELS = 20_000_000
MAX_EDGE = 10_000
MAX_CHARS = 60_000
FORMATS = {"PNG", "JPEG", "BMP", "WEBP", "TIFF"}

class OcrError(Exception):
    pass

def deny_network(*_args, **_kwargs):
    raise OcrError("offline")

def check_engine():
    try:
        if any(version(package) != pin for package, pin in PINS.items()):
            raise OcrError("engine")
    except PackageNotFoundError as exc:
        raise OcrError("engine") from exc
    spec = importlib.util.find_spec("rapidocr")
    if spec is None or not spec.origin:
        raise OcrError("engine")
    root = Path(spec.origin).parent / "models"
    paths = {}
    for task, (name, expected) in MODELS.items():
        path = root / name
        try:
            with path.open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != expected:
                    raise OcrError("weights")
        except OSError as exc:
            raise OcrError("weights") from exc
        paths[task] = str(path)
    return paths

def recognize(path, rotation):
    weights = check_engine()
    try:
        import cv2
        import numpy as np
        from PIL import Image, ImageOps, UnidentifiedImageError
        from rapidocr import RapidOCR, EngineType, LangDet, LangRec, ModelType, OCRVersion
        from rapidocr.utils.download_file import DownloadFile
    except ImportError as exc:
        raise OcrError("engine") from exc

    DownloadFile.run = deny_network
    try:
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise OcrError("image_size")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as source:
                if source.format not in FORMATS or getattr(source, "n_frames", 1) != 1:
                    raise OcrError("format")
                w, h = source.size
                if not w or not h or max(w, h) > MAX_EDGE or w * h > MAX_PIXELS:
                    raise OcrError("image_size")
                image = ImageOps.exif_transpose(source)
                if rotation:
                    image = image.rotate(-rotation, expand=True)
                if "A" in image.getbands() or "transparency" in image.info:
                    overlay = image.convert("RGBA")
                    image = Image.alpha_composite(Image.new("RGBA", overlay.size, "white"), overlay)
                pixels = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise OcrError("image_size") from exc
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise OcrError("decode") from exc

    cv2.setNumThreads(1)
    engine = RapidOCR(params={
        "EngineConfig.onnxruntime.intra_op_num_threads": 1,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        "EngineConfig.onnxruntime.use_cuda": False,
        "Det.engine_type": EngineType.ONNXRUNTIME, "Det.ocr_version": OCRVersion.PPOCRV6,
        "Det.model_type": ModelType.SMALL, "Det.lang_type": LangDet.CH,
        "Rec.engine_type": EngineType.ONNXRUNTIME, "Rec.ocr_version": OCRVersion.PPOCRV6,
        "Rec.model_type": ModelType.SMALL, "Rec.lang_type": LangRec.CH,
        **{f"{task}.model_path": path for task, path in weights.items()},
    })
    result = engine(pixels)
    lines = [str(x) for x in result.txts] if result.txts is not None else []
    text = "\n".join(x for x in lines if x.strip())
    return {"ok": True, "text": text[:MAX_CHARS], "truncated": len(text) > MAX_CHARS}

def main():
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[key] = "1"
    socket.create_connection = deny_network
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    socket.getaddrinfo = deny_network
    try:
        if sys.argv[1:] == ["--check"]:
            check_engine()
            import cv2
            import onnxruntime
            from PIL import Image
            result = {"ok": True}
        elif len(sys.argv) == 3 and sys.argv[2] in ("0", "90", "180", "270"):
            result = recognize(Path(sys.argv[1]), int(sys.argv[2]))
        else:
            raise OcrError("request")
    except OcrError as exc:
        result = {"ok": False, "error": str(exc)}
    except (ImportError, OSError):
        result = {"ok": False, "error": "engine"}
    except Exception:
        result = {"ok": False, "error": "recognition"}
    print(json.dumps(result, ensure_ascii=True))

if __name__ == "__main__":
    main()

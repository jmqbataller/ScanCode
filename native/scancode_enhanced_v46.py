from __future__ import annotations

import cv2
import numpy as np
import zxingcpp

from scancode_core import zoom_crop

_CALL_COUNTER = 0


def normalize_filter(filter_mode: str) -> str:
    value = str(filter_mode or "QR + Barcode").strip().lower()
    if value in {"qr", "qr only", "qrcode"}:
        return "qr"
    return "all"


def _decode_once(image: np.ndarray, filter_mode: str):
    if image is None or image.size == 0:
        return []
    try:
        found = zxingcpp.read_barcodes(
            image,
            try_rotate=True,
            try_downscale=True,
            try_invert=True,
        )
    except Exception:
        return []

    mode = normalize_filter(filter_mode)
    out = []
    seen = set()
    for barcode in found or []:
        text = str(getattr(barcode, "text", "") or "").strip()
        fmt = str(getattr(barcode, "format", "") or "").split(".")[-1]
        if not text:
            continue
        if mode == "qr" and fmt not in {"QRCode", "MicroQRCode"}:
            continue
        key = (text, fmt)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _gray_contrast(scan: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(scan, cv2.COLOR_BGR2GRAY) if scan.ndim == 3 else scan.copy()
    return cv2.createCLAHE(clipLimit=2.15, tileGridSize=(8, 8)).apply(gray)


def read_codes_optimized(frame: np.ndarray, filter_mode: str = "QR + Barcode", zoom: float = 1.75):
    """Low-CPU progressive QR/barcode decoder for warehouse webcams."""
    global _CALL_COUNTER
    if frame is None or frame.size == 0:
        return []

    _CALL_COUNTER = (_CALL_COUNTER + 1) % 1000000
    scan = zoom_crop(frame, max(1.0, float(zoom or 1.0)))

    # Fast path: original image, every scan cycle.
    result = _decode_once(scan, filter_mode)
    if result:
        return result

    # Light fallback: local contrast + mild sharpening.
    contrast = _gray_contrast(scan)
    blur = cv2.GaussianBlur(contrast, (0, 0), 1.0)
    sharp = cv2.addWeighted(contrast, 1.65, blur, -0.65, 0)
    result = _decode_once(sharp, filter_mode)
    if result:
        return result

    # Heavy recovery only every fourth failed cycle to reduce idle CPU load.
    if _CALL_COUNTER % 4 != 0:
        return []

    _, otsu = cv2.threshold(sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    result = _decode_once(otsu, filter_mode)
    if result:
        return result

    adaptive = cv2.adaptiveThreshold(
        sharp, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 31, 7,
    )
    result = _decode_once(adaptive, filter_mode)
    if result:
        return result

    h, w = sharp.shape[:2]
    if w < 2100:
        target_w = min(2160, int(w * 1.18))
        scale = target_w / float(max(1, w))
        enlarged = cv2.resize(
            sharp,
            (target_w, max(1, int(h * scale))),
            interpolation=cv2.INTER_CUBIC,
        )
        return _decode_once(enlarged, filter_mode)

    return []

from __future__ import annotations

import cv2
import numpy as np
import zxingcpp

from scancode_core import zoom_crop

SHIPPING_FORMATS = {
    "QRCode", "Code128", "Code39", "EAN13", "EAN8", "ITF", "DataMatrix",
    "PDF417", "UPCA", "UPCE", "Aztec", "Codabar", "Code93"
}


def _filter_results(found, filter_mode: str):
    out = []
    seen = set()
    for barcode in found or []:
        text = str(getattr(barcode, "text", "") or "").strip()
        fmt = str(getattr(barcode, "format", "") or "").split(".")[-1]
        if not text:
            continue
        if filter_mode == "qr" and fmt != "QRCode":
            continue
        if filter_mode == "shipping" and fmt not in SHIPPING_FORMATS:
            continue
        key = (text, fmt)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


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
    return _filter_results(found, filter_mode)


def _enhancement_variants(scan: np.ndarray):
    """Yield progressively stronger variants for fixed-focus / low-contrast webcams.

    The original image is intentionally not yielded here because the caller uses it
    as the fast path. Enhancement only runs when normal ZXing decoding fails.
    """
    if scan.ndim == 3:
        gray = cv2.cvtColor(scan, cv2.COLOR_BGR2GRAY)
    else:
        gray = scan.copy()

    # Local contrast makes black modules/bars stand out on white shipping labels,
    # especially under uneven warehouse lighting.
    clahe = cv2.createCLAHE(clipLimit=2.35, tileGridSize=(8, 8)).apply(gray)
    yield clahe

    # Unsharp masking recovers edge contrast from mild fixed-focus softness.
    blur = cv2.GaussianBlur(clahe, (0, 0), 1.15)
    sharpened = cv2.addWeighted(clahe, 1.85, blur, -0.85, 0)
    yield sharpened

    # Otsu works well for printed black-on-white QR/barcodes.
    _, otsu = cv2.threshold(sharpened, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield otsu

    # Adaptive threshold is a last fallback for glare/shadows across the label.
    adaptive = cv2.adaptiveThreshold(
        sharpened,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        7,
    )
    yield adaptive

    # Slight software enlargement can help small codes from a 1080p fixed-focus
    # camera. Cap the width so CPU use stays reasonable.
    h, w = sharpened.shape[:2]
    target_w = min(2304, int(w * 1.22))
    if target_w > w + 24:
        scale = target_w / float(w)
        enlarged = cv2.resize(
            sharpened,
            (target_w, max(1, int(h * scale))),
            interpolation=cv2.INTER_CUBIC,
        )
        yield enlarged


def read_codes_enhanced(frame: np.ndarray, filter_mode: str = "shipping", zoom: float = 1.75):
    """Decode QR/barcodes with a fast path plus fixed-focus enhancement fallbacks.

    This is optimized for 1080p webcams without autofocus. It cannot turn a truly
    out-of-focus image into a sharp one, but it substantially improves mild blur,
    low contrast, uneven light, and small printed codes.
    """
    if frame is None or frame.size == 0:
        return []

    scan = zoom_crop(frame, zoom)

    # Fast path: most clean codes should decode with one ZXing call.
    result = _decode_once(scan, filter_mode)
    if result:
        return result

    # Only pay the image-processing cost when the normal frame failed.
    for variant in _enhancement_variants(scan):
        result = _decode_once(variant, filter_mode)
        if result:
            return result

    return []

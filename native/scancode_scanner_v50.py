from __future__ import annotations

import time
from collections import deque

import cv2
import numpy as np

from scancode_core import zoom_crop
from scancode_enhanced_v46 import read_codes_optimized
from scancode_v5_services import choose_tracking_candidate


class SmartScanner:
    """Low-overhead scanner with ROI, adaptive zoom and candidate voting."""

    def __init__(self, settings_provider):
        self.settings_provider = settings_provider
        self.frame_no = 0
        self.recent = deque(maxlen=32)
        self.last_mode = "Near"
        self.last_success = 0.0

    @property
    def settings(self):
        try:
            return dict(self.settings_provider() or {})
        except Exception:
            return {}

    @staticmethod
    def scan_zone(frame: np.ndarray, ratio: float = 0.72):
        if frame is None or frame.size == 0:
            return frame
        ratio = min(0.96, max(0.35, float(ratio or 0.72)))
        h, w = frame.shape[:2]
        cw, ch = int(w * ratio), int(h * ratio)
        x1, y1 = (w - cw) // 2, (h - ch) // 2
        return frame[y1:y1 + ch, x1:x1 + cw]

    def _zooms(self, manual_zoom: float):
        s = self.settings
        if not bool(s.get("waybill_focus", True)):
            return [max(1.0, float(s.get("manual_scanner_zoom", manual_zoom) or manual_zoom))]
        mode = str(s.get("waybill_focus_mode", "Auto") or "Auto")
        if mode == "Near":
            return [1.35]
        if mode == "Far":
            return [2.15, 1.75]
        # Auto: use last successful mode first, then fallback. This keeps CPU low.
        if self.last_mode == "Far":
            return [2.15, 1.35]
        return [1.35, 2.15]

    def read(self, frame: np.ndarray, filter_mode: str = "QR + Barcode", zoom: float = 1.85):
        if frame is None or frame.size == 0:
            return []
        self.frame_no += 1
        s = self.settings
        zone_enabled = bool(s.get("smart_scan_zone", True))
        ratio = float(s.get("scan_zone_ratio", 0.72) or 0.72)
        source = self.scan_zone(frame, ratio) if zone_enabled else frame

        all_found = []
        zooms = self._zooms(zoom)
        for i, z in enumerate(zooms):
            # First attempt every scan pass; adaptive fallback is sampled to keep CPU low.
            if i > 0 and self.frame_no % 2:
                continue
            found = read_codes_optimized(source, filter_mode, z)
            if found:
                all_found.extend(found)
                self.last_mode = "Far" if z >= 1.9 else "Near"
                self.last_success = time.time()
                break

        # Full-frame rescue pass occasionally catches labels partly outside the zone.
        if not all_found and zone_enabled and self.frame_no % 5 == 0:
            all_found.extend(read_codes_optimized(frame, filter_mode, 1.45))

        if not all_found:
            return []

        # Preserve all unique results so the app can collect multiple barcode candidates.
        unique = []
        seen = set()
        for code, fmt in all_found:
            key = (str(code).strip(), str(fmt))
            if key in seen:
                continue
            seen.add(key)
            unique.append(key)
        return unique

    def best(self, detections):
        return choose_tracking_candidate(detections)


def draw_scan_zone(frame: np.ndarray, ratio: float = 0.72, label: str = "WAYBILL SCAN ZONE"):
    if frame is None or frame.size == 0:
        return frame
    out = frame.copy()
    ratio = min(0.96, max(0.35, float(ratio or 0.72)))
    h, w = out.shape[:2]
    cw, ch = int(w * ratio), int(h * ratio)
    x1, y1 = (w - cw) // 2, (h - ch) // 2
    x2, y2 = x1 + cw, y1 + ch
    thickness = max(2, int(min(w, h) / 360))
    cv2.rectangle(out, (x1, y1), (x2, y2), (230, 230, 230), thickness)
    cv2.putText(out, label, (x1 + 10, max(28, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (245, 245, 245), 2, cv2.LINE_AA)
    return out

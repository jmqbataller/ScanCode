from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import zxingcpp

VIDEO_EXT = ".avi"


def safe_name(value: str) -> str:
    value = str(value or "UNKNOWN").strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    value = re.sub(r"\s+", "_", value)
    return value[:100] or "UNKNOWN"


def day_name(ts: Optional[float] = None) -> str:
    d = datetime.fromtimestamp(ts or time.time())
    return d.strftime("%Y-%m-%d")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def unique_base(folder: Path, code: str) -> str:
    base = safe_name(code)
    candidate = base
    i = 2
    while any((folder / f"{candidate}{suffix}").exists() for suffix in (VIDEO_EXT, "_waybill.png", ".json", ".recording.avi")):
        candidate = f"{base}_{i}"
        i += 1
    return candidate


def zoom_crop(frame: np.ndarray, zoom: float = 1.0) -> np.ndarray:
    if frame is None or frame.size == 0:
        return frame
    zoom = max(1.0, float(zoom or 1.0))
    if zoom <= 1.001:
        return frame
    h, w = frame.shape[:2]
    cw, ch = max(1, int(w / zoom)), max(1, int(h / zoom))
    x1, y1 = (w - cw) // 2, (h - ch) // 2
    crop = frame[y1:y1 + ch, x1:x1 + cw]
    return cv2.resize(crop, (w, h), interpolation=cv2.INTER_LINEAR)


def read_codes(frame: np.ndarray, filter_mode: str = "shipping", zoom: float = 1.75):
    if frame is None or frame.size == 0:
        return []
    scan = zoom_crop(frame, zoom)
    try:
        found = zxingcpp.read_barcodes(scan, try_rotate=True, try_downscale=True, try_invert=True)
    except Exception:
        return []
    shipping = {
        "QRCode", "Code128", "Code39", "EAN13", "EAN8", "ITF", "DataMatrix",
        "PDF417", "UPCA", "UPCE", "Aztec", "Codabar", "Code93"
    }
    out = []
    for b in found:
        text = str(getattr(b, "text", "") or "").strip()
        fmt = str(getattr(b, "format", "") or "").split(".")[-1]
        if not text:
            continue
        if filter_mode == "qr" and fmt != "QRCode":
            continue
        if filter_mode == "shipping" and fmt not in shipping:
            continue
        out.append((text, fmt))
    return out


def camera_quality(frame: np.ndarray):
    if frame is None or frame.size == 0:
        return "NO FRAME", 0.0, 0.0
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))
    focus = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if brightness < 42:
        state = "TOO DARK"
    elif brightness > 225:
        state = "TOO BRIGHT"
    elif focus < 35:
        state = "CHECK FOCUS"
    else:
        state = "QUALITY GOOD"
    return state, brightness, focus


def waybill_crop(frame: np.ndarray, scanner_zoom: float = 1.75) -> np.ndarray:
    if frame is None or frame.size == 0:
        return frame
    source = zoom_crop(frame, scanner_zoom)
    gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, mask = cv2.threshold(blur, 170, 255, cv2.THRESH_BINARY)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = source.shape[:2]
    best = None
    best_score = 0
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        area = cw * ch
        if area < w * h * 0.06:
            continue
        aspect = cw / max(1, ch)
        if not (0.45 <= aspect <= 2.5):
            continue
        score = area
        if score > best_score:
            best_score, best = score, (x, y, cw, ch)
    if not best:
        return source
    x, y, cw, ch = best
    pad_x, pad_y = int(cw * 0.04), int(ch * 0.04)
    x1, y1 = max(0, x - pad_x), max(0, y - pad_y)
    x2, y2 = min(w, x + cw + pad_x), min(h, y + ch + pad_y)
    return source[y1:y2, x1:x2]


def overlay_frame(frame: np.ndarray, code: str, station: str, operator: str = "", recording: bool = True) -> np.ndarray:
    out = frame.copy()
    h, w = out.shape[:2]
    band_h = max(90, int(h * 0.17))
    overlay = out.copy()
    cv2.rectangle(overlay, (0, h - band_h), (w, h), (0, 0, 0), -1)
    out = cv2.addWeighted(overlay, 0.72, out, 0.28, 0)
    if recording:
        cv2.circle(out, (28, h - band_h + 28), 9, (25, 25, 230), -1)
        cv2.putText(out, "REC", (48, h - band_h + 36), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(out, safe_name(code), (24, h - band_h + 76), cv2.FONT_HERSHEY_SIMPLEX, 0.95, (255, 255, 255), 2, cv2.LINE_AA)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    footer = f"{station or 'Station 01'}  |  {stamp}"
    if operator:
        footer += f"  |  {operator}"
    cv2.putText(out, footer, (24, h - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (210, 210, 215), 1, cv2.LINE_AA)
    return out


@dataclass
class ParcelSession:
    code: str
    base: str
    folder: Path
    width: int
    height: int
    fps: float
    station: str
    operator: str
    started_at: float = field(default_factory=time.time)
    exception: str = ""
    stop_at: Optional[float] = None
    paused: bool = False
    writer: Optional[cv2.VideoWriter] = None
    temp_path: Path = field(init=False)
    final_path: Path = field(init=False)
    waybill_path: Path = field(init=False)
    metadata_path: Path = field(init=False)

    def __post_init__(self):
        self.temp_path = self.folder / f"{self.base}.recording.avi"
        self.final_path = self.folder / f"{self.base}{VIDEO_EXT}"
        self.waybill_path = self.folder / f"{self.base}_waybill.png"
        self.metadata_path = self.folder / f"{self.base}.json"
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        self.writer = cv2.VideoWriter(str(self.temp_path), fourcc, max(10.0, self.fps), (self.width, self.height))
        if not self.writer.isOpened():
            raise RuntimeError("Could not start the video recorder.")

    def write(self, frame: np.ndarray):
        if self.writer and not self.paused:
            self.writer.write(overlay_frame(frame, self.code, self.station, self.operator, True))

    def finalize(self):
        if self.writer:
            self.writer.release()
            self.writer = None
        if self.temp_path.exists():
            if self.final_path.exists():
                self.final_path.unlink(missing_ok=True)
            self.temp_path.replace(self.final_path)
        ended = time.time()
        metadata = {
            "code": self.code,
            "base": self.base,
            "startedAt": datetime.fromtimestamp(self.started_at).isoformat(),
            "endedAt": datetime.fromtimestamp(ended).isoformat(),
            "durationMs": int((ended - self.started_at) * 1000),
            "station": self.station,
            "operator": self.operator,
            "exception": self.exception or None,
            "videoFile": self.final_path.name,
            "waybillFile": self.waybill_path.name,
            "savedAt": datetime.now().isoformat(),
        }
        self.metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return metadata


def recover_recordings(root: Path):
    recovered = []
    if not root.exists():
        return recovered
    for p in root.rglob("*.recording.avi"):
        target = p.with_name(p.name.replace(".recording.avi", "_RECOVERED.avi"))
        i = 2
        while target.exists():
            target = p.with_name(p.name.replace(".recording.avi", f"_RECOVERED_{i}.avi"))
            i += 1
        try:
            p.replace(target)
            recovered.append(target)
        except Exception:
            pass
    return recovered


def pending_bundles(local_root: Path):
    bundles = []
    if not local_root.exists():
        return bundles
    for meta in local_root.rglob("*.json"):
        if meta.parent.name.startswith("."):
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            video = meta.parent / data.get("videoFile", "")
            waybill = meta.parent / data.get("waybillFile", "")
            if video.exists():
                bundles.append((meta, video, waybill if waybill.exists() else None))
        except Exception:
            continue
    return bundles


def sync_bundle(meta: Path, video: Path, waybill: Optional[Path], server_root: Path):
    day = meta.parent.name if re.fullmatch(r"\d{4}-\d{2}-\d{2}", meta.parent.name) else day_name()
    dest = server_root / day
    dest.mkdir(parents=True, exist_ok=True)
    files = [video, meta] + ([waybill] if waybill else [])
    copied = []
    for src in files:
        target = dest / src.name
        temp = dest / f".{src.name}.scancode-partial"
        shutil.copy2(src, temp)
        if temp.stat().st_size != src.stat().st_size or sha256_file(temp) != sha256_file(src):
            temp.unlink(missing_ok=True)
            raise IOError(f"Verification failed for {src.name}")
        temp.replace(target)
        copied.append((src, target))
    for src, _ in copied:
        src.unlink(missing_ok=True)
    return [str(t) for _, t in copied]

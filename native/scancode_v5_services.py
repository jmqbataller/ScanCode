from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np


COURIER_RULES = [
    ("J&T", re.compile(r"^(JT|JNT|7)[A-Z0-9-]{8,}$", re.I)),
    ("SPX", re.compile(r"^(SPX|SP|PH)[A-Z0-9-]{8,}$", re.I)),
    ("FLASH", re.compile(r"^(FLASH|FL|TH)[A-Z0-9-]{8,}$", re.I)),
    ("LAZADA", re.compile(r"^(LEX|LZD|LP)[A-Z0-9-]{8,}$", re.I)),
    ("NINJA VAN", re.compile(r"^(NJV|NINJA|NV)[A-Z0-9-]{8,}$", re.I)),
    ("2GO", re.compile(r"^(2GO)[A-Z0-9-]{8,}$", re.I)),
    ("LBC", re.compile(r"^(LBC)[A-Z0-9-]{8,}$", re.I)),
]

BARCODE_FORMAT_SCORE = {
    "Code128": 26,
    "QRCode": 24,
    "DataMatrix": 22,
    "PDF417": 20,
    "ITF": 18,
    "Code39": 17,
    "Code93": 16,
    "EAN13": 12,
    "EAN8": 9,
    "UPCA": 11,
    "UPCE": 9,
    "Codabar": 8,
    "Aztec": 16,
}


def normalize_code(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).upper()


def detect_courier(code: str) -> str:
    text = normalize_code(code)
    for courier, rule in COURIER_RULES:
        if rule.search(text):
            return courier
    if text.startswith("JT") or "JNT" in text:
        return "J&T"
    if text.startswith("SPX"):
        return "SPX"
    return "UNKNOWN"


def tracking_score(code: str, fmt: str = "") -> int:
    text = normalize_code(code)
    if len(text) < 6:
        return -100
    score = BARCODE_FORMAT_SCORE.get(str(fmt or "").split(".")[-1], 10)
    n = len(text)
    if 10 <= n <= 30:
        score += 24
    elif 8 <= n <= 40:
        score += 10
    else:
        score -= 12
    if detect_courier(text) != "UNKNOWN":
        score += 42
    if re.fullmatch(r"[A-Z0-9-]+", text):
        score += 8
    if re.fullmatch(r"\d{6,14}", text):
        score -= 4  # often SKU/order-id; still valid, but less likely than courier tracking
    if any(token in text for token in ("SKU", "ORDER", "ITEM", "QTY")):
        score -= 35
    return score


def choose_tracking_candidate(candidates: Iterable[tuple[str, str]]) -> tuple[str, str] | None:
    unique = {}
    for code, fmt in candidates:
        key = normalize_code(code)
        if not key:
            continue
        item = (key, str(fmt or "").split(".")[-1])
        if key not in unique or tracking_score(*item) > tracking_score(*unique[key]):
            unique[key] = item
    if not unique:
        return None
    return max(unique.values(), key=lambda x: tracking_score(*x))


def validate_tracking(code: str) -> tuple[bool, str]:
    text = normalize_code(code)
    if len(text) < 8:
        return False, "Tracking/barcode is too short."
    if len(text) > 64:
        return False, "Tracking/barcode is too long."
    if not re.fullmatch(r"[A-Z0-9._/-]+", text):
        return False, "Tracking/barcode contains unexpected characters."
    return True, "OK"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sharpness_score(frame: np.ndarray) -> float:
    if frame is None or getattr(frame, "size", 0) == 0:
        return 0.0
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def best_frame(frames: Iterable[np.ndarray]) -> np.ndarray | None:
    selected = None
    selected_score = -1.0
    for frame in frames:
        score = sharpness_score(frame)
        if score > selected_score:
            selected = frame
            selected_score = score
    return None if selected is None else selected.copy()


@dataclass
class SubmissionItem:
    code: str
    courier: str = "UNKNOWN"
    status: str = "QUEUED"
    attempts: int = 0
    last_error: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    def as_dict(self):
        now = time.time()
        return {
            "code": self.code,
            "courier": self.courier,
            "status": self.status,
            "attempts": int(self.attempts),
            "last_error": self.last_error,
            "created_at": float(self.created_at or now),
            "updated_at": float(self.updated_at or now),
        }


class SubmissionQueue:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write([])

    def _read(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _write(self, rows):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def enqueue(self, code: str, courier: str = "UNKNOWN", error: str = ""):
        code = normalize_code(code)
        rows = self._read()
        now = time.time()
        for row in rows:
            if row.get("code") == code and row.get("status") not in {"SUBMITTED", "VERIFIED"}:
                row["status"] = "QUEUED"
                row["last_error"] = error
                row["updated_at"] = now
                self._write(rows)
                return
        rows.append(SubmissionItem(code, courier, "QUEUED", 0, error, now, now).as_dict())
        self._write(rows)

    def update(self, code: str, status: str, error: str = "", increment_attempt: bool = False):
        rows = self._read()
        code = normalize_code(code)
        for row in rows:
            if row.get("code") == code:
                row["status"] = status
                row["last_error"] = error
                row["updated_at"] = time.time()
                if increment_attempt:
                    row["attempts"] = int(row.get("attempts") or 0) + 1
        self._write(rows)

    def pending(self):
        return [r for r in self._read() if r.get("status") not in {"SUBMITTED", "VERIFIED"}]

    def count(self):
        return len(self.pending())


class EvidenceDB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self):
        con = sqlite3.connect(self.path, timeout=8)
        con.row_factory = sqlite3.Row
        return con

    def _init(self):
        with self.connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS parcels (
                    code TEXT PRIMARY KEY,
                    courier TEXT,
                    operator TEXT,
                    station TEXT,
                    started_at REAL,
                    ended_at REAL,
                    duration_ms INTEGER DEFAULT 0,
                    video_path TEXT,
                    waybill_path TEXT,
                    metadata_path TEXT,
                    video_sha256 TEXT,
                    waybill_sha256 TEXT,
                    exception TEXT,
                    bigseller_status TEXT DEFAULT 'NOT_SENT',
                    bigseller_attempts INTEGER DEFAULT 0,
                    sync_status TEXT DEFAULT 'LOCAL',
                    quality_status TEXT DEFAULT 'PENDING',
                    integrity_status TEXT DEFAULT 'PENDING',
                    created_at REAL,
                    updated_at REAL
                );
                CREATE TABLE IF NOT EXISTS timeline (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT,
                    ts REAL,
                    event TEXT,
                    detail TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_timeline_code ON timeline(code, ts);
                CREATE INDEX IF NOT EXISTS idx_parcels_started ON parcels(started_at);
                CREATE INDEX IF NOT EXISTS idx_parcels_status ON parcels(bigseller_status);
                """
            )

    def event(self, code: str, event: str, detail: str = ""):
        with self.connect() as con:
            con.execute(
                "INSERT INTO timeline(code, ts, event, detail) VALUES(?,?,?,?)",
                (normalize_code(code), time.time(), event, str(detail or "")),
            )

    def upsert(self, record: dict):
        code = normalize_code(record.get("code"))
        if not code:
            return
        fields = {
            "code": code,
            "courier": record.get("courier", detect_courier(code)),
            "operator": record.get("operator", ""),
            "station": record.get("station", ""),
            "started_at": record.get("started_at", time.time()),
            "ended_at": record.get("ended_at"),
            "duration_ms": record.get("duration_ms", 0),
            "video_path": record.get("video_path", ""),
            "waybill_path": record.get("waybill_path", ""),
            "metadata_path": record.get("metadata_path", ""),
            "video_sha256": record.get("video_sha256", ""),
            "waybill_sha256": record.get("waybill_sha256", ""),
            "exception": record.get("exception", ""),
            "bigseller_status": record.get("bigseller_status", "NOT_SENT"),
            "bigseller_attempts": record.get("bigseller_attempts", 0),
            "sync_status": record.get("sync_status", "LOCAL"),
            "quality_status": record.get("quality_status", "PENDING"),
            "integrity_status": record.get("integrity_status", "PENDING"),
            "created_at": record.get("created_at", time.time()),
            "updated_at": time.time(),
        }
        names = list(fields)
        placeholders = ",".join("?" for _ in names)
        updates = ",".join(f"{n}=excluded.{n}" for n in names if n not in {"code", "created_at"})
        sql = f"INSERT INTO parcels({','.join(names)}) VALUES({placeholders}) ON CONFLICT(code) DO UPDATE SET {updates}"
        with self.connect() as con:
            con.execute(sql, [fields[n] for n in names])

    def update_status(self, code: str, **updates):
        allowed = {
            "courier", "operator", "station", "ended_at", "duration_ms", "video_path", "waybill_path",
            "metadata_path", "video_sha256", "waybill_sha256", "exception", "bigseller_status",
            "bigseller_attempts", "sync_status", "quality_status", "integrity_status"
        }
        clean = {k: v for k, v in updates.items() if k in allowed}
        if not clean:
            return
        clean["updated_at"] = time.time()
        cols = ",".join(f"{k}=?" for k in clean)
        with self.connect() as con:
            con.execute(f"UPDATE parcels SET {cols} WHERE code=?", list(clean.values()) + [normalize_code(code)])

    def exists(self, code: str) -> bool:
        with self.connect() as con:
            row = con.execute("SELECT 1 FROM parcels WHERE code=? LIMIT 1", (normalize_code(code),)).fetchone()
            return bool(row)

    def get(self, code: str):
        with self.connect() as con:
            row = con.execute("SELECT * FROM parcels WHERE code=?", (normalize_code(code),)).fetchone()
            return dict(row) if row else None

    def search(self, query: str, limit: int = 100):
        q = f"%{str(query or '').strip()}%"
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM parcels WHERE code LIKE ? OR courier LIKE ? OR operator LIKE ? ORDER BY started_at DESC LIMIT ?",
                (q, q, q, int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]

    def timeline(self, code: str):
        with self.connect() as con:
            rows = con.execute("SELECT ts,event,detail FROM timeline WHERE code=? ORDER BY ts", (normalize_code(code),)).fetchall()
            return [dict(r) for r in rows]

    def dashboard(self, since_hours: int = 24):
        since = time.time() - max(1, int(since_hours)) * 3600
        with self.connect() as con:
            total = con.execute("SELECT COUNT(*) c FROM parcels WHERE started_at>=?", (since,)).fetchone()[0]
            submitted = con.execute("SELECT COUNT(*) c FROM parcels WHERE started_at>=? AND bigseller_status IN ('SUBMITTED','VERIFIED')", (since,)).fetchone()[0]
            failed = con.execute("SELECT COUNT(*) c FROM parcels WHERE started_at>=? AND bigseller_status IN ('FAILED','QUEUED','PENDING_VERIFY')", (since,)).fetchone()[0]
            exceptions = con.execute("SELECT COUNT(*) c FROM parcels WHERE started_at>=? AND COALESCE(exception,'')<>''", (since,)).fetchone()[0]
            avg_ms = con.execute("SELECT COALESCE(AVG(duration_ms),0) FROM parcels WHERE started_at>=?", (since,)).fetchone()[0]
            operators = con.execute("SELECT operator,COUNT(*) c FROM parcels WHERE started_at>=? GROUP BY operator ORDER BY c DESC LIMIT 10", (since,)).fetchall()
        return {
            "total": int(total),
            "submitted": int(submitted),
            "failed": int(failed),
            "exceptions": int(exceptions),
            "avg_seconds": round(float(avg_ms or 0) / 1000.0, 1),
            "operators": [(r[0] or "Unassigned", int(r[1])) for r in operators],
        }


def patch_metadata(path: Path, **updates):
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        data = {}
    data.update(updates)
    data["updatedAt"] = datetime.now().isoformat()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def verify_integrity(video: Path | None, waybill: Path | None, expected_video: str = "", expected_waybill: str = ""):
    result = {"video": "MISSING", "waybill": "MISSING", "ok": True}
    if video and Path(video).exists():
        actual = sha256_file(Path(video))
        result["video"] = actual
        if expected_video and expected_video != actual:
            result["ok"] = False
    elif video:
        result["ok"] = False
    if waybill and Path(waybill).exists():
        actual = sha256_file(Path(waybill))
        result["waybill"] = actual
        if expected_waybill and expected_waybill != actual:
            result["ok"] = False
    elif waybill:
        result["ok"] = False
    return result


def cleanup_verified(records: Iterable[dict], retention_days: int = 14):
    cutoff = time.time() - max(1, int(retention_days)) * 86400
    deleted = []
    for row in records:
        if float(row.get("ended_at") or row.get("started_at") or time.time()) > cutoff:
            continue
        if row.get("sync_status") != "SYNCED" or row.get("integrity_status") != "VERIFIED":
            continue
        for key in ("video_path", "waybill_path", "metadata_path"):
            p = Path(row.get(key) or "")
            if p.exists() and p.is_file():
                try:
                    p.unlink()
                    deleted.append(str(p))
                except Exception:
                    pass
    return deleted


def format_timeline(rows: Iterable[dict]):
    lines = []
    for row in rows:
        stamp = datetime.fromtimestamp(float(row.get("ts") or 0)).strftime("%H:%M:%S")
        detail = str(row.get("detail") or "").strip()
        lines.append(f"{stamp}  {row.get('event','')}" + (f" — {detail}" if detail else ""))
    return "\n".join(lines)

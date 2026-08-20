from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import tkinter as tk
from PIL import Image, ImageTk
from tkinter import messagebox, simpledialog, ttk

import scancode_app as base_app
import scancode_app_v44 as v44
import scancode_app_v45 as v45
import scancode_app_v46 as v46
from scancode_core import pending_bundles, sync_bundle, waybill_crop, zoom_crop
from scancode_scanner_v50 import SmartScanner, draw_scan_zone
from scancode_v5_services import (
    EvidenceDB,
    SubmissionQueue,
    best_frame,
    choose_tracking_candidate,
    cleanup_verified,
    detect_courier,
    format_timeline,
    normalize_code,
    patch_metadata,
    sha256_file,
    validate_tracking,
    verify_integrity,
)

APP_VERSION = "5.0.0"
base_app.APP_VERSION = APP_VERSION
v44.APP_VERSION = APP_VERSION
v45.APP_VERSION = APP_VERSION
v46.APP_VERSION = APP_VERSION


class ScanCodeApp(v46.ScanCodeApp):
    """ScanCode v5 warehouse packing evidence + BigSeller workstation."""

    def __init__(self, root: tk.Tk, start_services: bool = True):
        self.auto_session_var = tk.BooleanVar(master=root, value=True)
        self.smart_zone_var = tk.BooleanVar(master=root, value=True)
        self.best_waybill_var = tk.BooleanVar(master=root, value=True)
        self.quality_check_var = tk.BooleanVar(master=root, value=True)
        self.voice_var = tk.BooleanVar(master=root, value=False)
        self.require_operator_var = tk.BooleanVar(master=root, value=False)
        self.bigseller_verify_var = tk.BooleanVar(master=root, value=True)
        self.bigseller_retry_var = tk.BooleanVar(master=root, value=True)
        self.duplicate_protection_var = tk.BooleanVar(master=root, value=True)
        self.output_action_var = tk.StringVar(master=root, value="Enter")
        self.retention_var = tk.StringVar(master=root, value="14")
        self.pre_record_var = tk.StringVar(master=root, value="5")
        self.min_record_var = tk.StringVar(master=root, value="3")
        self.supervisor_locked = False
        self._candidate_buffer = []
        self._candidate_flush_pending = False
        self._frame_buffer = deque(maxlen=180)
        self._last_health_update = 0.0
        self._retry_stop = threading.Event()
        self._cleanup_stop = threading.Event()
        self._current_courier = "UNKNOWN"
        self._last_submission_status = {}
        super().__init__(root, start_services=start_services)

        self.ops_root = base_app.app_data_dir() / "v5"
        self.ops_root.mkdir(parents=True, exist_ok=True)
        self.db = EvidenceDB(self.ops_root / "evidence.db")
        self.submit_queue = SubmissionQueue(self.ops_root / "bigseller_queue.json")
        self.smart_scanner = SmartScanner(lambda: self.settings)
        # Base camera worker resolves this module global dynamically, so a bound
        # method is valid and gives the decoder access to live v5 settings.
        base_app.read_codes = self.smart_scanner.read

        if start_services:
            threading.Thread(target=self._submission_retry_worker, daemon=True).start()
            threading.Thread(target=self._maintenance_worker, daemon=True).start()
            self.root.after(900, self._maybe_auto_arm)

    def defaults(self):
        data = super().defaults()
        data.update({
            "scan_target": "BigSeller",
            "barcode_filter": "QR + Barcode",
            "waybill_focus_mode": "Auto",
            "auto_pack_session": True,
            "smart_scan_zone": True,
            "scan_zone_ratio": 0.72,
            "best_waybill_shot": True,
            "pre_record_seconds": 5,
            "minimum_record_seconds": 3,
            "packing_quality_check": True,
            "duplicate_protection": True,
            "voice_feedback": False,
            "require_operator": False,
            "bigseller_verify": True,
            "bigseller_retry": True,
            "bigseller_retry_interval": 15,
            "output_action": "Enter",
            "retention_days": 14,
            "auto_cleanup": True,
            "camera_health": True,
            "courier_detection": True,
            "supervisor_pin": "",
            "supervisor_lock": False,
        })
        return data

    def load_settings(self):
        data = super().load_settings()
        defaults = self.defaults()
        for key, value in defaults.items():
            data.setdefault(key, value)
        old_focus = data.get("waybill_focus_mode", "Auto")
        if old_focus not in {"Auto", "Near", "Far"}:
            old_focus = "Auto"
        data["waybill_focus_mode"] = old_focus
        data["barcode_filter"] = "QR + Barcode" if str(data.get("barcode_filter", "")).lower() not in {"qr", "qr only"} else "QR only"
        return data

    def save_settings(self):
        super().save_settings()
        try:
            self.settings.update({
                "auto_pack_session": bool(self.auto_session_var.get()),
                "smart_scan_zone": bool(self.smart_zone_var.get()),
                "best_waybill_shot": bool(self.best_waybill_var.get()),
                "packing_quality_check": bool(self.quality_check_var.get()),
                "voice_feedback": bool(self.voice_var.get()),
                "require_operator": bool(self.require_operator_var.get()),
                "bigseller_verify": bool(self.bigseller_verify_var.get()),
                "bigseller_retry": bool(self.bigseller_retry_var.get()),
                "duplicate_protection": bool(self.duplicate_protection_var.get()),
                "output_action": self.output_action_var.get() or "Enter",
                "retention_days": max(1, int(self.retention_var.get() or 14)),
                "pre_record_seconds": max(0, min(10, int(self.pre_record_var.get() or 5))),
                "minimum_record_seconds": max(0, int(self.min_record_var.get() or 3)),
            })
            self.settings_path.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except Exception:
            pass

    def combo_row(self, parent, label, variable, values):
        if label == "Barcode filter":
            # v5 replaces the older filter row with production-focused controls.
            v44.ScanCodeApp.combo_row(self, parent, "Scan formats", variable, ["QR + Barcode", "QR only"])
            self.check(parent, "Enable camera autofocus (if supported)", self.autofocus_var)
            self.check(parent, "Enable Waybill Focus", self.waybill_focus_var)
            row = tk.Frame(parent, bg=base_app.PANEL)
            row.pack(fill="x", padx=14, pady=3)
            self.label(row, "Waybill distance", 8, False, base_app.MUTED).pack(anchor="w")
            combo = ttk.Combobox(row, textvariable=self.waybill_focus_mode_var, state="readonly", values=["Auto", "Near", "Far"])
            combo.pack(fill="x")
            combo.bind("<<ComboboxSelected>>", lambda e: self._focus_setting_changed())
            tk.Label(
                parent,
                text="Auto tries the most likely Near/Far crop first. Near keeps a wider label area; Far tightens the center crop.",
                bg=base_app.PANEL, fg=base_app.MUTED, font=("Segoe UI", 8), wraplength=285, justify="left",
            ).pack(anchor="w", padx=14, pady=(3, 5))
            return
        return super().combo_row(parent, label, variable, values)

    def build_side(self):
        super().build_side()
        panel = self.panel(self.side)
        self.label(panel, "V5 PACKING AUTOMATION", 8, True, base_app.MUTED).pack(anchor="w", padx=14, pady=(12, 5))
        self.check(panel, "Automatic packing session", self.auto_session_var)
        self.check(panel, "Smart waybill scan zone", self.smart_zone_var)
        self.check(panel, "Best waybill photo", self.best_waybill_var)
        self.check(panel, "Packing quality checklist", self.quality_check_var)
        self.check(panel, "Duplicate parcel protection", self.duplicate_protection_var)
        self.check(panel, "BigSeller verify after submit", self.bigseller_verify_var)
        self.check(panel, "Retry failed BigSeller queue", self.bigseller_retry_var)
        self.check(panel, "Voice feedback", self.voice_var)
        self.check(panel, "Require operator name", self.require_operator_var)
        self.combo_row(panel, "After paste", self.output_action_var, ["Enter", "Tab", "None"])
        self.entry_row(panel, "Pre-record buffer (seconds)", self.pre_record_var)
        self.entry_row(panel, "Minimum packing video (seconds)", self.min_record_var)
        self.entry_row(panel, "Keep verified local evidence (days)", self.retention_var)
        row = tk.Frame(panel, bg=base_app.PANEL)
        row.pack(fill="x", padx=14, pady=(7, 5))
        self.button(row, "Evidence Center", self.open_evidence_center, True).pack(side="left", fill="x", expand=True)
        self.button(row, "Retry Queue", self.retry_all_submissions).pack(side="left", fill="x", expand=True, padx=(6, 0))
        row2 = tk.Frame(panel, bg=base_app.PANEL)
        row2.pack(fill="x", padx=14, pady=(0, 6))
        self.button(row2, "Verify Evidence", self.verify_selected_or_recent).pack(side="left", fill="x", expand=True)
        self.button(row2, "Storage Cleanup", self.run_storage_cleanup).pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.button(panel, "Supervisor Lock / Unlock", self.toggle_supervisor).pack(fill="x", padx=14, pady=(0, 12))

        health = self.panel(self.side)
        self.label(health, "CAMERA / OPERATIONS HEALTH", 8, True, base_app.MUTED).pack(anchor="w", padx=14, pady=(10, 3))
        self.health_status = self.label(health, "Waiting for camera…", 8, False, base_app.MUTED)
        self.health_status.pack(anchor="w", padx=14, pady=(0, 10))

    def apply_settings_to_ui(self):
        super().apply_settings_to_ui()
        s = self.settings
        self.auto_session_var.set(bool(s.get("auto_pack_session", True)))
        self.smart_zone_var.set(bool(s.get("smart_scan_zone", True)))
        self.best_waybill_var.set(bool(s.get("best_waybill_shot", True)))
        self.quality_check_var.set(bool(s.get("packing_quality_check", True)))
        self.voice_var.set(bool(s.get("voice_feedback", False)))
        self.require_operator_var.set(bool(s.get("require_operator", False)))
        self.bigseller_verify_var.set(bool(s.get("bigseller_verify", True)))
        self.bigseller_retry_var.set(bool(s.get("bigseller_retry", True)))
        self.duplicate_protection_var.set(bool(s.get("duplicate_protection", True)))
        self.output_action_var.set(str(s.get("output_action", "Enter")))
        self.retention_var.set(str(s.get("retention_days", 14)))
        self.pre_record_var.set(str(s.get("pre_record_seconds", 5)))
        self.min_record_var.set(str(s.get("minimum_record_seconds", 3)))
        self.waybill_focus_mode_var.set(str(s.get("waybill_focus_mode", "Auto")))

    # ------------------------------------------------------------------
    # Scanning intelligence / automatic parcel sessions
    # ------------------------------------------------------------------
    def _maybe_auto_arm(self):
        if self.settings.get("auto_pack_session", True) and not self.system_running:
            if self.settings.get("require_operator") and not self.operator_var.get().strip():
                return
            self.start_stop()
            self.toast("Automatic packing session armed.")

    def start_stop(self):
        if not self.system_running and self.settings.get("require_operator", False) and not self.operator_var.get().strip():
            return self.toast("Enter operator name before starting.")
        return super().start_stop()

    def handle_barcode(self, code, fmt):
        if not self.system_running or self.system_paused:
            return
        self._candidate_buffer.append((str(code), str(fmt), time.time()))
        cutoff = time.time() - 0.55
        self._candidate_buffer = [x for x in self._candidate_buffer if x[2] >= cutoff]
        if not self._candidate_flush_pending:
            self._candidate_flush_pending = True
            self.root.after(160, self._flush_candidates)

    def _flush_candidates(self):
        self._candidate_flush_pending = False
        recent = [(c, f) for c, f, ts in self._candidate_buffer if time.time() - ts <= 0.75]
        best = choose_tracking_candidate(recent)
        if not best:
            return
        code, fmt = best
        # Let the proven v4 confirmation / duplicate timing gate finish the job.
        super().handle_barcode(code, fmt)

    def accept_scan(self, raw_code):
        code = normalize_code(raw_code)
        valid, reason = validate_tracking(code)
        if not valid:
            self._feedback("invalid")
            return self.toast(reason)

        courier = detect_courier(code) if self.settings.get("courier_detection", True) else "UNKNOWN"
        self._current_courier = courier
        if hasattr(self, "db") and self.settings.get("duplicate_protection", True) and self.db.exists(code):
            self._feedback("duplicate")
            self.db.event(code, "DUPLICATE_BLOCKED", "Duplicate scan prevented")
            return self.toast(f"DUPLICATE: {code} already has evidence.")

        buffered = self._decode_buffer_frames()
        result = super().accept_scan(code)
        session = self.current_session
        if not session:
            return result

        # Inject compressed pre-record history into the newly created evidence video.
        for frame in buffered:
            try:
                session.write(frame)
            except Exception:
                break

        if self.settings.get("best_waybill_shot", True):
            best = best_frame(buffered[-30:] if buffered else [])
            if best is not None:
                try:
                    focus_zoom = float(self.settings.get("scanner_zoom", 1.85) or 1.85)
                    cv2.imwrite(str(session.waybill_path), waybill_crop(best, focus_zoom))
                except Exception:
                    pass

        if hasattr(self, "db"):
            self.db.upsert({
                "code": code,
                "courier": courier,
                "operator": self.operator_var.get().strip(),
                "station": self.station_var.get().strip() or "Station 01",
                "started_at": session.started_at,
                "video_path": str(session.final_path),
                "waybill_path": str(session.waybill_path),
                "metadata_path": str(session.metadata_path),
                "bigseller_status": "QUEUED" if self.settings.get("scan_target") == "BigSeller" else "NOT_SENT",
                "quality_status": "RECORDING",
            })
            self.db.event(code, "WAYBILL_SCANNED", f"{courier} / {fmt if 'fmt' in locals() else ''}")
            self.db.event(code, "RECORDING_STARTED", f"Pre-buffer {len(buffered)} frames")
        self.detail_status.configure(text=f"RECORDING • {courier}", fg=base_app.RED)
        return result

    def write_sessions(self, frame, fps):
        # Memory-safe pre-record: JPEG-compress a small 720p copy instead of keeping
        # raw 1080p frames. At ~8 FPS, 5 seconds stays modest in RAM.
        try:
            seconds = max(0, min(10, int(self.settings.get("pre_record_seconds", 5) or 5)))
            max_items = max(1, seconds * 8)
            if self._frame_buffer.maxlen != max_items:
                self._frame_buffer = deque(self._frame_buffer, maxlen=max_items)
            if seconds and int(time.time() * 8) % 1 == 0:
                h, w = frame.shape[:2]
                scale = min(1.0, 1280.0 / max(1, w))
                small = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else frame
                ok, buf = cv2.imencode(".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), 68])
                if ok:
                    self._frame_buffer.append(buf.tobytes())
        except Exception:
            pass
        return super().write_sessions(frame, fps)

    def _decode_buffer_frames(self):
        frames = []
        for raw in list(self._frame_buffer):
            try:
                arr = np.frombuffer(raw, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    frames.append(frame)
            except Exception:
                pass
        return frames

    # ------------------------------------------------------------------
    # Evidence finalization, quality, integrity and timeline
    # ------------------------------------------------------------------
    def finalize_session(self, session):
        try:
            ended = time.time()
            duration_ms = int((ended - session.started_at) * 1000)
            session.finalize()
            video_hash = sha256_file(session.final_path) if session.final_path.exists() else ""
            waybill_hash = sha256_file(session.waybill_path) if session.waybill_path.exists() else ""
            min_sec = int(self.settings.get("minimum_record_seconds", 3) or 3)
            checks = {
                "waybill_scanned": bool(session.code),
                "video_recorded": session.final_path.exists(),
                "minimum_duration": duration_ms >= min_sec * 1000,
                "waybill_photo": session.waybill_path.exists(),
            }
            quality = "PASS" if all(checks.values()) else "REVIEW"
            courier = detect_courier(session.code)
            submission = self._last_submission_status.get(session.code, "PENDING")
            patch_metadata(
                session.metadata_path,
                courier=courier,
                packingQuality=quality,
                packingChecks=checks,
                videoSha256=video_hash,
                waybillSha256=waybill_hash,
                bigSellerStatus=submission,
                appVersion=APP_VERSION,
            )
            if hasattr(self, "db"):
                self.db.upsert({
                    "code": session.code,
                    "courier": courier,
                    "operator": session.operator,
                    "station": session.station,
                    "started_at": session.started_at,
                    "ended_at": ended,
                    "duration_ms": duration_ms,
                    "video_path": str(session.final_path),
                    "waybill_path": str(session.waybill_path),
                    "metadata_path": str(session.metadata_path),
                    "video_sha256": video_hash,
                    "waybill_sha256": waybill_hash,
                    "exception": session.exception,
                    "bigseller_status": submission,
                    "quality_status": quality,
                    "integrity_status": "VERIFIED" if video_hash and waybill_hash else "REVIEW",
                })
                self.db.event(session.code, "RECORDING_FINALIZED", f"{duration_ms/1000:.1f}s / quality {quality}")
                self.db.event(session.code, "EVIDENCE_HASHED", "SHA-256 stored")
            self.events.put(("saved", session))
            self._feedback("saved")
        except Exception as exc:
            self.events.put(("error", f"Could not save {session.code}: {exc}"))

    # ------------------------------------------------------------------
    # BigSeller submission, verification, wrong-window guard and retry queue
    # ------------------------------------------------------------------
    def _output_keys(self):
        action = str(self.settings.get("output_action", "Enter") or "Enter")
        if action == "Tab":
            return "^v{TAB}"
        if action == "None":
            return "^v"
        return "^v{ENTER}"

    def submit_active_app(self, code):
        clean = normalize_code(code)
        base_app.pyperclip.copy(clean)
        if os.name != "nt" or base_app.send_keys is None:
            return self.events.put(("bigseller", f"Copied {clean}; UI automation unavailable."))
        target = self._foreground_window_info()
        if not target or int(target.get("pid") or 0) == os.getpid():
            return self.events.put(("bigseller", f"Copied {clean}; focus another app/input."))
        try:
            base_app.send_keys(self._output_keys(), pause=.02)
            self.events.put(("bigseller", f"Pasted {clean} → {target.get('title') or 'active app'}."))
        except Exception as exc:
            self.events.put(("bigseller", f"Copied {clean}; active-app paste failed: {exc}"))

    def _find_bigseller_window(self):
        if base_app.Desktop is None:
            return None
        try:
            wins = [w for w in base_app.Desktop(backend="uia").windows() if "bigseller" in (w.window_text() or "").lower() and w.is_visible()]
            return wins[0] if wins else None
        except Exception:
            return None

    def _choose_bigseller_input(self, win):
        try:
            edits = [e for e in win.descendants(control_type="Edit") if e.is_visible() and e.is_enabled()]
        except Exception:
            return None
        if not edits:
            return None
        def score(edit):
            text = ""
            try:
                text = f"{edit.window_text()} {edit.element_info.name} {edit.element_info.automation_id}".lower()
            except Exception:
                pass
            points = 0
            for token, value in (("tracking", 20), ("waybill", 20), ("scan", 16), ("parcel", 12), ("package", 10), ("order", 5)):
                if token in text:
                    points += value
            try:
                rect = edit.rectangle()
                points -= int(rect.top / 10000)
            except Exception:
                pass
            return points
        return max(edits, key=score)

    def submit_bigseller(self, code):
        clean = normalize_code(code)
        courier = detect_courier(clean)
        if hasattr(self, "submit_queue"):
            self.submit_queue.enqueue(clean, courier)
            self.submit_queue.update(clean, "SUBMITTING", increment_attempt=True)
        if hasattr(self, "db"):
            self.db.event(clean, "BIGSELLER_ATTEMPT", "UI Automation")
            row = self.db.get(clean) or {}
            self.db.update_status(clean, bigseller_status="SUBMITTING", bigseller_attempts=int(row.get("bigseller_attempts") or 0) + 1)

        base_app.pyperclip.copy(clean)
        if base_app.Desktop is None or base_app.send_keys is None:
            return self._submission_failed(clean, "Windows UI Automation unavailable")
        win = self._find_bigseller_window()
        if not win:
            return self._submission_failed(clean, "BigSeller is not open. Scan held in retry queue.")

        try:
            win.set_focus()
            target = self._choose_bigseller_input(win)
            if not target:
                return self._submission_failed(clean, "BigSeller tracking input was not exposed to UI Automation")
            target.click_input()
            base_app.send_keys("^a", pause=.02)
            base_app.send_keys(self._output_keys(), pause=.03)
            status, detail = self._verify_bigseller(win, target, clean)
            self._last_submission_status[clean] = status
            if hasattr(self, "submit_queue"):
                self.submit_queue.update(clean, status)
            if hasattr(self, "db"):
                self.db.update_status(clean, bigseller_status=status)
                self.db.event(clean, "BIGSELLER_" + status, detail)
            self.events.put(("bigseller", f"BigSeller {status}: {clean} — {detail}"))
            self._feedback("submitted" if status in {"SUBMITTED", "VERIFIED"} else "warning")
        except Exception as exc:
            self._submission_failed(clean, str(exc))

    def _verify_bigseller(self, win, target, code):
        if not self.settings.get("bigseller_verify", True):
            return "SUBMITTED", "Verification disabled"
        time.sleep(0.55)
        texts = []
        try:
            for element in win.descendants()[-120:]:
                try:
                    text = (element.window_text() or "").strip()
                    if text:
                        texts.append(text.lower())
                except Exception:
                    pass
        except Exception:
            pass
        joined = " | ".join(texts)
        success_words = ("success", "submitted", "processed", "completed", "scanned successfully")
        fail_words = ("invalid tracking", "submit failed", "scan failed", "not found", "error")
        if any(word in joined for word in fail_words):
            return "FAILED", "BigSeller displayed an error message"
        if any(word in joined for word in success_words):
            return "VERIFIED", "BigSeller success message detected"
        try:
            current = (target.window_text() or "").strip()
            if normalize_code(current) != code:
                return "SUBMITTED", "Input changed/cleared after submit"
        except Exception:
            pass
        return "PENDING_VERIFY", "Submission sent; no explicit success message detected"

    def _submission_failed(self, code, reason):
        self._last_submission_status[code] = "QUEUED"
        if hasattr(self, "submit_queue"):
            self.submit_queue.enqueue(code, detect_courier(code), reason)
            self.submit_queue.update(code, "QUEUED", reason)
        if hasattr(self, "db"):
            self.db.update_status(code, bigseller_status="QUEUED")
            self.db.event(code, "BIGSELLER_QUEUED", reason)
        self.events.put(("bigseller", f"QUEUED: {code} — {reason}"))
        self._feedback("failed")

    def _submission_retry_worker(self):
        while not self._retry_stop.is_set():
            interval = max(10, int(self.settings.get("bigseller_retry_interval", 15) or 15))
            if self.settings.get("bigseller_retry", True) and hasattr(self, "submit_queue") and self._find_bigseller_window():
                for row in self.submit_queue.pending()[:5]:
                    if self._retry_stop.is_set():
                        break
                    try:
                        self.submit_bigseller(row.get("code", ""))
                    except Exception:
                        pass
                    time.sleep(.4)
            self._retry_stop.wait(interval)

    def retry_all_submissions(self):
        if not hasattr(self, "submit_queue"):
            return
        count = self.submit_queue.count()
        self.toast(f"Retry queue: {count} parcel(s).")
        threading.Thread(target=self._retry_pending_now, daemon=True).start()

    def _retry_pending_now(self):
        for row in self.submit_queue.pending():
            if self._retry_stop.is_set():
                break
            self.submit_bigseller(row.get("code", ""))
            time.sleep(.35)

    # ------------------------------------------------------------------
    # Audio / voice / camera health / preview scan-zone overlay
    # ------------------------------------------------------------------
    def _feedback(self, kind):
        if self.settings.get("sound", True) and base_app.winsound:
            patterns = {
                "duplicate": [(360, 100), (300, 140)],
                "invalid": [(260, 180)],
                "failed": [(280, 150), (280, 150), (220, 200)],
                "warning": [(500, 100), (400, 120)],
                "submitted": [(950, 70), (1250, 80)],
                "saved": [(800, 60), (1050, 70)],
            }
            seq = patterns.get(kind, [(850, 60)])
            threading.Thread(target=lambda: [base_app.winsound.Beep(f, d) for f, d in seq], daemon=True).start()
        if self.settings.get("voice_feedback", False) and os.name == "nt":
            phrase = {
                "duplicate": "Duplicate parcel",
                "invalid": "Invalid barcode",
                "failed": "Big Seller submission failed",
                "submitted": "Big Seller submitted",
                "saved": "Parcel saved",
            }.get(kind)
            if phrase:
                safe = phrase.replace("'", "")
                cmd = f"Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{safe}')"
                try:
                    subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", cmd], creationflags=0x08000000)
                except Exception:
                    pass

    def ui_tick(self):
        with self.frame_lock:
            frame = None if self.latest_frame is None else self.latest_frame.copy()
        if frame is not None:
            far = zoom_crop(frame, float(self.far_zoom_var.get() or 1))
            if self.settings.get("smart_scan_zone", True):
                far = draw_scan_zone(far, float(self.settings.get("scan_zone_ratio", 0.72) or 0.72))
            rgb = cv2.cvtColor(far, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            vw = max(320, self.video_label.winfo_width())
            vh = max(220, self.video_label.winfo_height())
            img.thumbnail((vw, vh), Image.Resampling.LANCZOS)
            self.preview_photo = ImageTk.PhotoImage(img)
            self.video_label.configure(image=self.preview_photo, text="")

            if hasattr(self, "health_status") and time.time() - self._last_health_update > 1.2:
                self._last_health_update = time.time()
                try:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    brightness = float(np.mean(gray))
                    focus = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                    h, w = frame.shape[:2]
                    fps = float(self.capture.get(cv2.CAP_PROP_FPS) or 0) if self.capture else 0
                    focus_state = "GOOD" if focus >= 35 else "SOFT"
                    light_state = "GOOD" if 45 <= brightness <= 220 else ("DARK" if brightness < 45 else "BRIGHT")
                    queue_count = self.submit_queue.count() if hasattr(self, "submit_queue") else 0
                    self.health_status.configure(text=f"{w}x{h} • {fps:.0f} FPS • Focus {focus_state} • Light {light_state} • BigSeller Q{queue_count}")
                except Exception:
                    pass
        self.root.after(55, self.ui_tick)

    # ------------------------------------------------------------------
    # Verified server sync with retention instead of immediate deletion
    # ------------------------------------------------------------------
    def _copy_bundle_keep_local(self, meta: Path, video: Path, waybill: Path | None, server: Path):
        day = meta.parent.name
        dest = server / day
        dest.mkdir(parents=True, exist_ok=True)
        for src in [video, meta] + ([waybill] if waybill else []):
            if src is None or not src.exists():
                continue
            temp = dest / f".{src.name}.scancode-partial"
            target = dest / src.name
            shutil.copy2(src, temp)
            if temp.stat().st_size != src.stat().st_size or sha256_file(temp) != sha256_file(src):
                temp.unlink(missing_ok=True)
                raise IOError(f"Verification failed for {src.name}")
            temp.replace(target)
        if hasattr(self, "db"):
            self.db.update_status(meta.stem, sync_status="SYNCED")
            self.db.event(meta.stem, "SERVER_SYNCED", str(dest))

    def one_sync(self):
        server = Path(self.server_var.get().strip()) if self.server_var.get().strip() else None
        if not server or not server.exists():
            return self.events.put(("sync", ("SERVER OFFLINE", "Server not reachable", len(pending_bundles(self.local_root)))))
        for meta, video, waybill in pending_bundles(self.local_root):
            try:
                self._copy_bundle_keep_local(meta, video, waybill, server)
            except Exception as exc:
                self.events.put(("error", str(exc)))
                break
        self.events.put(("sync", ("SERVER ONLINE", "Verified copy retained locally", len(pending_bundles(self.local_root)))))

    def sync_worker(self):
        while not self.sync_stop.is_set():
            try:
                bundles = pending_bundles(self.local_root)
                server = Path(self.settings.get("server_folder") or "") if self.settings.get("server_folder") else None
                if not server:
                    self.events.put(("sync", ("SERVER NOT SET", "Configure server folder", len(bundles))))
                elif not server.exists():
                    self.events.put(("sync", ("SERVER OFFLINE", "Files remain local", len(bundles))))
                elif not self.settings.get("auto_sync", True):
                    self.events.put(("sync", ("SYNC OFF", "Auto Sync disabled", len(bundles))))
                else:
                    for meta, video, waybill in bundles:
                        if self.sync_stop.is_set():
                            break
                        try:
                            self._copy_bundle_keep_local(meta, video, waybill, server)
                        except Exception as exc:
                            self.events.put(("error", f"Sync failed: {exc}"))
                            break
                    self.events.put(("sync", ("SERVER ONLINE", "Verified copy retained locally", 0)))
            except Exception as exc:
                self.events.put(("error", f"Server sync error: {exc}"))
            self.sync_stop.wait(15)

    # ------------------------------------------------------------------
    # Evidence center, dashboard, one-click playback, timeline, storage
    # ------------------------------------------------------------------
    def open_evidence_center(self):
        if not hasattr(self, "db"):
            return self.toast("Evidence database is starting.")
        win = tk.Toplevel(self.root)
        win.title("ScanCode v5 — Evidence Center")
        win.geometry("980x650")
        win.configure(bg=base_app.BG)
        top = tk.Frame(win, bg=base_app.PANEL)
        top.pack(fill="x", padx=10, pady=10)
        qvar = tk.StringVar()
        entry = tk.Entry(top, textvariable=qvar, bg=base_app.PANEL2, fg=base_app.TEXT, insertbackground=base_app.TEXT, relief="flat")
        entry.pack(side="left", fill="x", expand=True, ipady=7)
        stats = self.db.dashboard(24)
        summary = self.label(win, f"24H  Packed {stats['total']}  •  Submitted {stats['submitted']}  •  Queue/Failed {stats['failed']}  •  Exceptions {stats['exceptions']}  •  Avg {stats['avg_seconds']}s", 9, True, base_app.MUTED, base_app.BG)
        summary.pack(anchor="w", padx=12, pady=(0, 7))
        body = tk.Frame(win, bg=base_app.BG)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        left = tk.Frame(body, bg=base_app.PANEL)
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(body, bg=base_app.PANEL, width=390)
        right.pack(side="left", fill="both", padx=(10, 0))
        right.pack_propagate(False)
        listing = tk.Listbox(left, bg="#0c0c0f", fg=base_app.TEXT, selectbackground=base_app.RED, relief="flat")
        listing.pack(fill="both", expand=True, padx=8, pady=8)
        detail = tk.Text(right, bg="#0c0c0f", fg=base_app.TEXT, insertbackground=base_app.TEXT, relief="flat", wrap="word")
        detail.pack(fill="both", expand=True, padx=8, pady=8)
        rows = []

        def refresh():
            nonlocal rows
            rows = self.db.search(qvar.get(), 200)
            listing.delete(0, "end")
            for r in rows:
                stamp = time.strftime("%m-%d %H:%M", time.localtime(float(r.get("started_at") or 0)))
                listing.insert("end", f"{stamp}  {r.get('code')}  {r.get('courier')}  {r.get('bigseller_status')}")

        def show(_event=None):
            sel = listing.curselection()
            if not sel:
                return
            r = rows[sel[0]]
            timeline = format_timeline(self.db.timeline(r.get("code", "")))
            detail.delete("1.0", "end")
            detail.insert("end", json.dumps(r, indent=2) + "\n\nTIMELINE\n" + timeline)

        def play():
            sel = listing.curselection()
            if not sel:
                return
            p = Path(rows[sel[0]].get("video_path") or "")
            if p.exists() and os.name == "nt":
                os.startfile(str(p))
            else:
                self.toast("Local video not found. Check server copy.")

        self.button(top, "Search", refresh, True).pack(side="left", padx=(7, 0))
        self.button(top, "Play Video", play).pack(side="left", padx=(7, 0))
        listing.bind("<<ListboxSelect>>", show)
        listing.bind("<Double-Button-1>", lambda e: play())
        entry.bind("<Return>", lambda e: refresh())
        refresh()

    def verify_selected_or_recent(self):
        code = self.current_session.code if self.current_session else (self.last_accepted.get("code") if self.last_accepted else None)
        if not code or not hasattr(self, "db"):
            return self.toast("No recent parcel to verify.")
        row = self.db.get(code)
        if not row:
            return self.toast("Parcel is not in the evidence index yet.")
        result = verify_integrity(Path(row.get("video_path") or ""), Path(row.get("waybill_path") or ""), row.get("video_sha256") or "", row.get("waybill_sha256") or "")
        status = "VERIFIED" if result.get("ok") else "FAILED"
        self.db.update_status(code, integrity_status=status)
        self.db.event(code, "INTEGRITY_" + status, "Manual verification")
        self.toast(f"Evidence integrity: {status}.")

    def run_storage_cleanup(self):
        if not hasattr(self, "db"):
            return
        days = max(1, int(self.settings.get("retention_days", 14) or 14))
        rows = self.db.search("", 10000)
        deleted = cleanup_verified(rows, days)
        self.toast(f"Storage cleanup removed {len(deleted)} verified file(s).")

    def _maintenance_worker(self):
        while not self._cleanup_stop.wait(3600):
            if self.settings.get("auto_cleanup", True):
                try:
                    self.run_storage_cleanup()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Supervisor controls / exceptions / shutdown
    # ------------------------------------------------------------------
    def toggle_supervisor(self):
        pin = str(self.settings.get("supervisor_pin") or "")
        if not pin:
            new_pin = simpledialog.askstring("Supervisor Setup", "Create supervisor PIN (leave blank to cancel):", show="*", parent=self.root)
            if not new_pin:
                return
            self.settings["supervisor_pin"] = str(new_pin)
            self.settings["supervisor_lock"] = True
            self.supervisor_locked = True
            self.settings_path.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
            return self.toast("Supervisor lock enabled.")
        if self.supervisor_locked or self.settings.get("supervisor_lock", False):
            entered = simpledialog.askstring("Supervisor", "Enter supervisor PIN:", show="*", parent=self.root)
            if str(entered or "") != pin:
                return self.toast("Incorrect supervisor PIN.")
            self.supervisor_locked = False
            self.settings["supervisor_lock"] = False
            self.toast("Supervisor settings unlocked.")
        else:
            self.supervisor_locked = True
            self.settings["supervisor_lock"] = True
            self.toast("Supervisor settings locked.")
        try:
            self.settings_path.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except Exception:
            pass

    def mark_exception(self):
        result = super().mark_exception()
        if self.current_session and hasattr(self, "db"):
            self.db.update_status(self.current_session.code, exception=self.current_session.exception)
            self.db.event(self.current_session.code, "EXCEPTION", self.current_session.exception)
        return result

    def on_close(self):
        self._retry_stop.set()
        self._cleanup_stop.set()
        return super().on_close()


def main():
    root = tk.Tk()
    ScanCodeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

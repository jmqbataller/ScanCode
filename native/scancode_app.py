from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import webbrowser
from pathlib import Path

import cv2
import numpy as np
import pyperclip
import tkinter as tk
from PIL import Image, ImageTk
from tkinter import filedialog, messagebox, ttk

try:
    import winsound
except Exception:
    winsound = None

try:
    import winreg
except Exception:
    winreg = None

try:
    from pywinauto import Desktop
    from pywinauto.keyboard import send_keys
except Exception:
    Desktop = None
    send_keys = None

from scancode_core import (
    ParcelSession, camera_quality, day_name, pending_bundles, read_codes,
    recover_recordings, safe_name, sync_bundle, unique_base, waybill_crop,
    zoom_crop,
)

APP_VERSION = "4.0.0"
APP_NAME = "ScanCode"
RED = "#d51f2a"
DARK_RED = "#8f151c"
BG = "#09090b"
PANEL = "#121216"
PANEL2 = "#18181d"
BORDER = "#303038"
TEXT = "#f4f4f5"
MUTED = "#a3a3ad"
GREEN = "#24b36b"
AMBER = "#d89b29"


def app_data_dir() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home()))
    p = base / "ScanCode"
    p.mkdir(parents=True, exist_ok=True)
    return p


def documents_root() -> Path:
    p = Path.home() / "Documents" / "ScanCode"
    p.mkdir(parents=True, exist_ok=True)
    return p


class ScanCodeApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"ScanCode {APP_VERSION} — John Mark Bataller")
        self.root.geometry("1320x820")
        self.root.minsize(680, 480)
        self.root.configure(bg=BG)

        self.settings_path = app_data_dir() / "settings.json"
        self.local_root = documents_root()
        self.settings = self.load_settings()
        self.events = queue.Queue()
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.sessions_lock = threading.Lock()
        self.capture = None
        self.camera_thread = None
        self.camera_stop = threading.Event()
        self.camera_live = False
        self.last_frame_at = 0.0
        self.current_session: ParcelSession | None = None
        self.ending_sessions: list[ParcelSession] = []
        self.scan_candidate = {"code": None, "count": 0, "at": 0.0}
        self.last_accepted = {"code": None, "at": 0.0}
        self.saved_count = 0
        self.sync_stop = threading.Event()
        self.sync_thread = None
        self.preview_photo = None
        self.compact_auto = False

        recovered = recover_recordings(self.local_root)
        self.build_style()
        self.build_ui()
        self.apply_settings_to_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Configure>", self.on_resize)
        self.root.bind("<F1>", lambda e: self.start_resume())
        self.root.bind("<F2>", lambda e: self.pause_resume())
        self.root.bind("<F3>", lambda e: self.stop_recording())

        if recovered:
            self.toast(f"Recovered {len(recovered)} interrupted video(s).")

        self.start_camera()
        self.start_sync_worker()
        self.root.after(25, self.ui_tick)
        self.root.after(150, self.event_tick)

    def defaults(self):
        return {
            "station": "Station 01",
            "operator": "",
            "camera_index": 0,
            "network_url": "",
            "camera_mode": "PC / USB Camera",
            "far_zoom": 1.0,
            "scanner_zoom": 1.75,
            "scan_confirmations": 2,
            "barcode_filter": "shipping",
            "overlap_ms": 900,
            "sound": True,
            "quality": True,
            "server_folder": "",
            "auto_sync": True,
            "auto_start": False,
            "bigseller_url": "",
            "bigseller_auto": True,
        }

    def load_settings(self):
        data = self.defaults()
        try:
            if self.settings_path.exists():
                data.update(json.loads(self.settings_path.read_text(encoding="utf-8")))
        except Exception:
            pass
        return data

    def save_settings(self):
        self.settings.update({
            "station": self.station_var.get().strip() or "Station 01",
            "operator": self.operator_var.get().strip(),
            "camera_index": int(self.camera_var.get() or 0),
            "network_url": self.network_var.get().strip(),
            "camera_mode": self.mode_var.get(),
            "far_zoom": float(self.far_zoom_var.get()),
            "scanner_zoom": float(self.scanner_zoom_var.get()),
            "scan_confirmations": int(self.confirm_var.get()),
            "barcode_filter": self.filter_var.get(),
            "overlap_ms": int(self.overlap_var.get()),
            "sound": bool(self.sound_var.get()),
            "quality": bool(self.quality_var.get()),
            "server_folder": self.server_var.get().strip(),
            "auto_sync": bool(self.auto_sync_var.get()),
            "auto_start": bool(self.auto_start_var.get()),
            "bigseller_url": self.bigseller_var.get().strip(),
            "bigseller_auto": bool(self.bigseller_auto_var.get()),
        })
        try:
            self.settings_path.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except Exception:
            pass
        self.set_windows_autostart(self.settings["auto_start"])

    def build_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2, foreground=TEXT,
                        arrowcolor=TEXT, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL2)], foreground=[("readonly", TEXT)])
        style.configure("Horizontal.TScale", background=PANEL, troughcolor="#28282f")

    def button(self, parent, text, command, primary=False, width=None):
        b = tk.Button(parent, text=text, command=command, bg=RED if primary else PANEL2,
                      fg=TEXT, activebackground=DARK_RED if primary else "#24242b",
                      activeforeground=TEXT, relief="flat", bd=0, padx=14, pady=9,
                      font=("Segoe UI", 10, "bold"), cursor="hand2")
        if width:
            b.configure(width=width)
        return b

    def label(self, parent, text="", size=10, bold=False, fg=TEXT, bg=PANEL):
        return tk.Label(parent, text=text, fg=fg, bg=bg,
                        font=("Segoe UI", size, "bold" if bold else "normal"))

    def build_ui(self):
        top = tk.Frame(self.root, bg=PANEL, height=78, highlightbackground=BORDER, highlightthickness=1)
        top.pack(fill="x")
        brand = tk.Frame(top, bg=PANEL); brand.pack(side="left", padx=22, pady=14)
        self.label(brand, "WAREHOUSE UTILITY", 8, True, MUTED).pack(anchor="w")
        title_row = tk.Frame(brand, bg=PANEL); title_row.pack(anchor="w")
        self.label(title_row, "ScanCode", 19, True).pack(side="left")
        self.label(title_row, f"  v{APP_VERSION} NATIVE", 8, True, RED).pack(side="left", pady=(7,0))

        badges = tk.Frame(top, bg=PANEL); badges.pack(side="right", padx=18)
        self.camera_badge = self.make_badge(badges, "CAMERA STARTING")
        self.quality_badge = self.make_badge(badges, "QUALITY —")
        self.server_badge = self.make_badge(badges, "SERVER NOT SET")
        self.record_badge = self.make_badge(badges, "NOT RECORDING")

        self.main = tk.Frame(self.root, bg=BG)
        self.main.pack(fill="both", expand=True, padx=12, pady=12)

        self.left = tk.Frame(self.main, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        self.left.pack(side="left", fill="both", expand=True)
        self.side = tk.Frame(self.main, bg=BG, width=330)
        self.side.pack(side="right", fill="y", padx=(12,0))
        self.side.pack_propagate(False)

        controls = tk.Frame(self.left, bg=PANEL); controls.pack(fill="x", padx=16, pady=14)
        self.label(controls, "Live Camera", 13, True).grid(row=0, column=0, sticky="w", columnspan=4)
        self.label(controls, "Native OpenCV camera • QR/barcode scanner • evidence recorder", 9, False, MUTED).grid(row=1, column=0, sticky="w", pady=(2,10), columnspan=4)

        self.mode_var = tk.StringVar()
        mode = ttk.Combobox(controls, textvariable=self.mode_var, state="readonly", values=["PC / USB Camera", "Phone / Network Camera"], width=22)
        mode.grid(row=2, column=0, sticky="ew", padx=(0,8))
        mode.bind("<<ComboboxSelected>>", lambda e: self.camera_source_changed())
        self.camera_var = tk.StringVar()
        cam = ttk.Combobox(controls, textvariable=self.camera_var, state="readonly", values=[str(i) for i in range(6)], width=8)
        cam.grid(row=2, column=1, sticky="ew", padx=(0,8))
        cam.bind("<<ComboboxSelected>>", lambda e: self.restart_camera())
        self.network_var = tk.StringVar()
        self.network_entry = tk.Entry(controls, textvariable=self.network_var, bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat")
        self.network_entry.grid(row=2, column=2, sticky="ew", padx=(0,8))
        self.button(controls, "Restart camera", self.restart_camera).grid(row=2, column=3, sticky="ew")
        controls.columnconfigure(0, weight=1); controls.columnconfigure(2, weight=2)

        self.video_border = tk.Frame(self.left, bg=BORDER, padx=2, pady=2)
        self.video_border.pack(fill="both", expand=True, padx=8)
        self.video_label = tk.Label(self.video_border, bg="#000000", fg=TEXT, text="Starting native camera…", font=("Segoe UI", 12, "bold"))
        self.video_label.pack(fill="both", expand=True)

        transport = tk.Frame(self.left, bg=PANEL); transport.pack(fill="x", padx=16, pady=10)
        self.button(transport, "Start / Resume", self.start_resume, True).pack(side="left", padx=(0,8))
        self.button(transport, "Pause", self.pause_resume).pack(side="left", padx=(0,8))
        self.button(transport, "Stop", self.stop_recording, True).pack(side="left")
        self.transport_status = self.label(transport, "Waiting for scan", 9, True, MUTED)
        self.transport_status.pack(side="right")

        manual = tk.Frame(self.left, bg=PANEL); manual.pack(fill="x", padx=16, pady=(0,14))
        self.manual_var = tk.StringVar()
        manual_entry = tk.Entry(manual, textvariable=self.manual_var, bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat", font=("Segoe UI",10))
        manual_entry.pack(side="left", fill="x", expand=True, ipady=8)
        manual_entry.bind("<Return>", lambda e: self.manual_scan())
        self.button(manual, "Simulate Scan", self.manual_scan, True).pack(side="left", padx=(8,0))

        self.build_side()
        self.build_history_search()

        self.toast_label = tk.Label(self.root, text="", bg="#1d1d22", fg=TEXT, padx=14, pady=8, font=("Segoe UI",9,"bold"))

    def make_badge(self, parent, text):
        l = tk.Label(parent, text=text, bg=PANEL2, fg=MUTED, padx=10, pady=7, font=("Segoe UI",8,"bold"))
        l.pack(side="left", padx=4)
        return l

    def set_badge(self, badge, text, state="neutral"):
        colors = {"good": GREEN, "bad": "#ff6b71", "warn": AMBER, "neutral": MUTED}
        badge.configure(text=text, fg=colors.get(state, MUTED))

    def panel(self, parent):
        p = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        p.pack(fill="x", pady=(0,10))
        return p

    def build_side(self):
        parcel = self.panel(self.side)
        self.label(parcel, "ACTIVE PARCEL", 8, True, MUTED).pack(anchor="w", padx=14, pady=(12,2))
        self.current_code = self.label(parcel, "Waiting for scan", 14, True); self.current_code.pack(anchor="w", padx=14)
        self.detail_status = self.label(parcel, "IDLE", 9, True, MUTED); self.detail_status.pack(anchor="w", padx=14, pady=(4,10))
        self.exception_var = tk.StringVar(value="")
        ex = ttk.Combobox(parcel, textvariable=self.exception_var, state="readonly", values=["", "DAMAGED", "WRONG_ITEM", "MISSING_ITEM", "BARCODE_UNREADABLE", "PACKING_ISSUE", "FOR_SUPERVISOR"])
        ex.pack(fill="x", padx=14, pady=(0,6))
        self.button(parcel, "Mark Exception", self.mark_exception, True).pack(fill="x", padx=14, pady=(0,12))

        settings = self.panel(self.side)
        self.label(settings, "STATION / SCANNER", 8, True, MUTED).pack(anchor="w", padx=14, pady=(12,4))
        self.station_var = tk.StringVar(); self.operator_var = tk.StringVar()
        self.entry_row(settings, "Station", self.station_var)
        self.entry_row(settings, "Operator", self.operator_var)

        self.sound_var = tk.BooleanVar(); self.quality_var = tk.BooleanVar(); self.auto_start_var = tk.BooleanVar()
        self.check(settings, "Scan success sound", self.sound_var)
        self.check(settings, "Camera quality check", self.quality_var)
        self.check(settings, "Auto-start with Windows", self.auto_start_var)

        self.confirm_var = tk.StringVar(); self.filter_var = tk.StringVar(); self.overlap_var = tk.StringVar()
        self.combo_row(settings, "Scan confirmation", self.confirm_var, ["1","2","3"])
        self.combo_row(settings, "Barcode filter", self.filter_var, ["shipping","qr","all"])
        self.combo_row(settings, "Overlap ms", self.overlap_var, ["500","900","1500","2000"])

        self.far_zoom_var = tk.DoubleVar(); self.scanner_zoom_var = tk.DoubleVar()
        self.scale_row(settings, "FAR / Recording Zoom", self.far_zoom_var, 1.0, 1.75)
        self.scale_row(settings, "NEAR / Scanner Zoom", self.scanner_zoom_var, 1.0, 3.0)
        self.button(settings, "Save settings", self.save_settings, True).pack(fill="x", padx=14, pady=(8,12))

        server = self.panel(self.side)
        self.label(server, "SERVER TRANSFER", 8, True, MUTED).pack(anchor="w", padx=14, pady=(12,4))
        self.server_var = tk.StringVar(); self.auto_sync_var = tk.BooleanVar()
        self.entry_row(server, "Server folder", self.server_var)
        self.check(server, "Auto Sync", self.auto_sync_var)
        row = tk.Frame(server, bg=PANEL); row.pack(fill="x", padx=14, pady=(4,10))
        self.button(row, "Choose", self.choose_server).pack(side="left", fill="x", expand=True)
        self.button(row, "Sync now", self.sync_now).pack(side="left", fill="x", expand=True, padx=(6,0))
        self.server_status = self.label(server, "Not configured", 8, False, MUTED); self.server_status.pack(anchor="w", padx=14, pady=(0,10))

        big = self.panel(self.side)
        self.label(big, "BIGSELLER BRIDGE", 8, True, MUTED).pack(anchor="w", padx=14, pady=(12,4))
        self.bigseller_var = tk.StringVar(); self.bigseller_auto_var = tk.BooleanVar()
        self.entry_row(big, "Page URL", self.bigseller_var)
        self.check(big, "Auto-submit scanned code", self.bigseller_auto_var)
        self.button(big, "Open BigSeller", self.open_bigseller).pack(fill="x", padx=14, pady=(4,6))
        self.bigseller_status = self.label(big, "UI Automation beta", 8, False, MUTED); self.bigseller_status.pack(anchor="w", padx=14, pady=(0,10))

        self.button(self.side, "End-of-shift verification", self.end_shift, True).pack(fill="x")

    def build_history_search(self):
        bottom = tk.Frame(self.root, bg=BG)
        bottom.pack(fill="x", padx=12, pady=(0,12))
        self.bottom = bottom
        hist = tk.Frame(bottom, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        hist.pack(side="left", fill="both", expand=True)
        self.label(hist, "Session History", 11, True).pack(anchor="w", padx=12, pady=(8,4))
        self.history = tk.Listbox(hist, bg="#0c0c0f", fg=TEXT, selectbackground=RED, relief="flat", height=5)
        self.history.pack(fill="both", expand=True, padx=10, pady=(0,10))
        self.history.bind("<Double-Button-1>", lambda e: self.open_history_item())
        search = tk.Frame(bottom, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, width=430)
        search.pack(side="right", fill="both", padx=(10,0)); search.pack_propagate(False)
        self.label(search, "Server Parcel Search", 11, True).pack(anchor="w", padx=12, pady=(8,4))
        sr = tk.Frame(search, bg=PANEL); sr.pack(fill="x", padx=10)
        self.search_var = tk.StringVar(); tk.Entry(sr, textvariable=self.search_var, bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat").pack(side="left", fill="x", expand=True, ipady=5)
        self.button(sr, "Search", self.search_server, True).pack(side="left", padx=(6,0))
        self.search_results = tk.Listbox(search, bg="#0c0c0f", fg=TEXT, selectbackground=RED, relief="flat", height=5)
        self.search_results.pack(fill="both", expand=True, padx=10, pady=8)
        self.search_results.bind("<Double-Button-1>", lambda e: self.open_search_item())
        self.search_paths = []

    def entry_row(self, parent, label, variable):
        f=tk.Frame(parent,bg=PANEL);f.pack(fill="x",padx=14,pady=3)
        self.label(f,label,8,False,MUTED).pack(anchor="w")
        tk.Entry(f,textvariable=variable,bg=PANEL2,fg=TEXT,insertbackground=TEXT,relief="flat").pack(fill="x",ipady=5)

    def combo_row(self, parent, label, variable, values):
        f=tk.Frame(parent,bg=PANEL);f.pack(fill="x",padx=14,pady=3)
        self.label(f,label,8,False,MUTED).pack(anchor="w")
        ttk.Combobox(f,textvariable=variable,state="readonly",values=values).pack(fill="x")

    def scale_row(self, parent, label, variable, minv, maxv):
        f=tk.Frame(parent,bg=PANEL);f.pack(fill="x",padx=14,pady=3)
        self.label(f,label,8,False,MUTED).pack(anchor="w")
        ttk.Scale(f,variable=variable,from_=minv,to=maxv,orient="horizontal",command=lambda e:self.save_settings()).pack(fill="x")

    def check(self, parent, text, variable):
        c=tk.Checkbutton(parent,text=text,variable=variable,bg=PANEL,fg=TEXT,activebackground=PANEL,activeforeground=TEXT,selectcolor=PANEL2,command=self.save_settings)
        c.pack(anchor="w",padx=14,pady=2)

    def apply_settings_to_ui(self):
        s=self.settings
        self.station_var.set(s["station"]);self.operator_var.set(s["operator"]);self.camera_var.set(str(s["camera_index"]));self.network_var.set(s["network_url"]);self.mode_var.set(s["camera_mode"])
        self.far_zoom_var.set(s["far_zoom"]);self.scanner_zoom_var.set(s["scanner_zoom"]);self.confirm_var.set(str(s["scan_confirmations"]));self.filter_var.set(s["barcode_filter"]);self.overlap_var.set(str(s["overlap_ms"]))
        self.sound_var.set(s["sound"]);self.quality_var.set(s["quality"]);self.server_var.set(s["server_folder"]);self.auto_sync_var.set(s["auto_sync"]);self.auto_start_var.set(s["auto_start"]);self.bigseller_var.set(s["bigseller_url"]);self.bigseller_auto_var.set(s["bigseller_auto"])

    def camera_source_changed(self):
        self.save_settings(); self.restart_camera()

    def restart_camera(self):
        self.save_settings(); self.stop_camera(); self.root.after(250,self.start_camera)

    def start_camera(self):
        self.camera_stop.clear()
        self.camera_thread=threading.Thread(target=self.camera_worker,daemon=True)
        self.camera_thread.start()
        self.set_badge(self.camera_badge,"CAMERA STARTING","warn")

    def stop_camera(self):
        self.camera_stop.set()
        if self.capture:
            try:self.capture.release()
            except Exception:pass
        self.capture=None;self.camera_live=False

    def open_capture(self):
        mode=self.mode_var.get()
        if mode=="Phone / Network Camera":
            url=self.network_var.get().strip()
            if not url:raise RuntimeError("Network camera URL is empty.")
            cap=cv2.VideoCapture(url)
            if not cap.isOpened():raise RuntimeError("Could not open network camera URL.")
            return cap
        idx=int(self.camera_var.get() or 0)
        backends=[cv2.CAP_DSHOW,cv2.CAP_MSMF,cv2.CAP_ANY]
        last=None
        for backend in backends:
            cap=cv2.VideoCapture(idx,backend)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,1280);cap.set(cv2.CAP_PROP_FRAME_HEIGHT,720);cap.set(cv2.CAP_PROP_FPS,30)
            try:cap.set(cv2.CAP_PROP_AUTOFOCUS,1)
            except Exception:pass
            if cap.isOpened():
                for _ in range(12):
                    ok,frame=cap.read()
                    if ok and frame is not None and frame.size:
                        return cap
                    time.sleep(.05)
            last=cap;cap.release()
        raise RuntimeError(f"Windows could not open camera index {idx} with DirectShow/MSMF.")

    def camera_worker(self):
        retry=0
        while not self.camera_stop.is_set():
            try:
                self.capture=self.open_capture();self.camera_live=True;self.events.put(("camera_live",None));retry=0
                fps=float(self.capture.get(cv2.CAP_PROP_FPS) or 25);fps=fps if 5<=fps<=60 else 25
                frame_no=0
                while not self.camera_stop.is_set():
                    ok,frame=self.capture.read()
                    if not ok or frame is None:
                        raise RuntimeError("Camera stopped returning frames.")
                    self.last_frame_at=time.time();frame_no+=1
                    with self.frame_lock:self.latest_frame=frame.copy()
                    far=zoom_crop(frame,float(self.far_zoom_var.get() or 1))
                    self.write_sessions(far,fps)
                    if frame_no%3==0:
                        for code,fmt in read_codes(frame,self.filter_var.get(),float(self.scanner_zoom_var.get() or 1.75)):
                            self.events.put(("barcode",(code,fmt)))
                    if self.quality_var.get() and frame_no%30==0:
                        self.events.put(("quality",camera_quality(frame)))
                break
            except Exception as exc:
                self.camera_live=False;self.events.put(("camera_error",str(exc)));retry+=1
                try:self.capture.release()
                except Exception:pass
                self.capture=None
                if self.camera_stop.wait(min(5,1+retry)):break

    def write_sessions(self,frame,fps):
        finalize=[]
        now=time.time()
        with self.sessions_lock:
            sessions=([self.current_session] if self.current_session else [])+list(self.ending_sessions)
            for s in sessions:
                if not s:continue
                try:s.write(frame)
                except Exception as exc:self.events.put(("error",f"Recording write failed: {exc}"))
            for s in list(self.ending_sessions):
                if s.stop_at is not None and now>=s.stop_at:
                    self.ending_sessions.remove(s);finalize.append(s)
        for s in finalize:self.finalize_session(s)

    def handle_barcode(self,code,fmt):
        now=time.time();needed=max(1,int(self.confirm_var.get() or 2))
        if self.scan_candidate["code"]==code and now-self.scan_candidate["at"]<1.2:self.scan_candidate["count"]+=1
        else:self.scan_candidate={"code":code,"count":1,"at":now}
        self.scan_candidate["at"]=now
        if self.scan_candidate["count"]>=needed:
            self.scan_candidate={"code":None,"count":0,"at":0};self.accept_scan(code)

    def accept_scan(self,raw_code):
        code=str(raw_code).strip()
        if len(code)<3:return
        now=time.time()
        if self.current_session and self.current_session.code==code:return
        if self.last_accepted["code"]==code and now-self.last_accepted["at"]<1.4:return
        with self.frame_lock:frame=None if self.latest_frame is None else self.latest_frame.copy()
        if frame is None:return self.toast("Camera frame not ready.")
        self.last_accepted={"code":code,"at":now}
        day=self.local_root/day_name();day.mkdir(parents=True,exist_ok=True);base=unique_base(day,code)
        h,w=frame.shape[:2]
        fps=25.0
        if self.capture:
            v=float(self.capture.get(cv2.CAP_PROP_FPS) or 25);fps=v if 5<=v<=60 else 25
        try:new=ParcelSession(code,base,day,w,h,fps,self.station_var.get().strip() or "Station 01",self.operator_var.get().strip())
        except Exception as exc:return self.toast(str(exc))
        crop=waybill_crop(frame,float(self.scanner_zoom_var.get() or 1.75));cv2.imwrite(str(new.waybill_path),crop)
        with self.sessions_lock:
            old=self.current_session
            if old:
                old.stop_at=time.time()+int(self.overlap_var.get() or 900)/1000.0;self.ending_sessions.append(old)
            self.current_session=new
        self.current_code.configure(text=code);self.detail_status.configure(text="RECORDING",fg=RED);self.transport_status.configure(text=f"Recording • {code}",fg=TEXT);self.video_border.configure(bg=RED);self.set_badge(self.record_badge,"● RECORDING","bad")
        if self.sound_var.get() and winsound:
            threading.Thread(target=lambda:(winsound.Beep(880,70),winsound.Beep(1180,80)),daemon=True).start()
        if self.bigseller_auto_var.get():threading.Thread(target=self.submit_bigseller,args=(code,),daemon=True).start()

    def manual_scan(self):
        code=self.manual_var.get().strip()
        if code:self.manual_var.set("");self.accept_scan(code)

    def start_resume(self):
        if self.current_session:
            self.current_session.paused=False;self.set_badge(self.record_badge,"● RECORDING","bad");self.transport_status.configure(text=f"Recording • {self.current_session.code}")
        else:
            code=self.manual_var.get().strip() or f"MANUAL-{int(time.time())}";self.accept_scan(code)

    def pause_resume(self):
        if not self.current_session:return self.toast("No active recording.")
        self.current_session.paused=not self.current_session.paused
        if self.current_session.paused:self.set_badge(self.record_badge,"PAUSED","warn");self.transport_status.configure(text=f"Paused • {self.current_session.code}")
        else:self.set_badge(self.record_badge,"● RECORDING","bad");self.transport_status.configure(text=f"Recording • {self.current_session.code}")

    def stop_recording(self):
        with self.sessions_lock:
            if not self.current_session:return self.toast("No active recording.")
            s=self.current_session;self.current_session=None;s.stop_at=time.time();self.ending_sessions.append(s)
        self.current_code.configure(text="Waiting for scan");self.detail_status.configure(text="IDLE",fg=MUTED);self.transport_status.configure(text="Waiting for scan",fg=MUTED);self.video_border.configure(bg=BORDER);self.set_badge(self.record_badge,"NOT RECORDING","neutral")

    def finalize_session(self,s):
        try:
            s.finalize();self.events.put(("saved",s))
        except Exception as exc:self.events.put(("error",f"Could not save {s.code}: {exc}"))

    def mark_exception(self):
        if not self.current_session:return self.toast("Scan a parcel first.")
        self.current_session.exception=self.exception_var.get();self.toast("Exception updated.")

    def ui_tick(self):
        with self.frame_lock:frame=None if self.latest_frame is None else self.latest_frame.copy()
        if frame is not None:
            far=zoom_crop(frame,float(self.far_zoom_var.get() or 1))
            rgb=cv2.cvtColor(far,cv2.COLOR_BGR2RGB);img=Image.fromarray(rgb)
            vw=max(320,self.video_label.winfo_width());vh=max(220,self.video_label.winfo_height())
            img.thumbnail((vw,vh),Image.Resampling.LANCZOS)
            self.preview_photo=ImageTk.PhotoImage(img);self.video_label.configure(image=self.preview_photo,text="")
        self.root.after(30,self.ui_tick)

    def event_tick(self):
        try:
            while True:
                kind,data=self.events.get_nowait()
                if kind=="barcode":self.handle_barcode(*data)
                elif kind=="camera_live":self.set_badge(self.camera_badge,"CAMERA LIVE","good");self.toast("Native camera is live.")
                elif kind=="camera_error":self.set_badge(self.camera_badge,"CAMERA ERROR","bad");self.video_label.configure(text=f"CAMERA ERROR\n{data}",image="");
                elif kind=="quality":self.set_badge(self.quality_badge,data[0],"good" if data[0]=="QUALITY GOOD" else "warn")
                elif kind=="saved":self.saved_count+=1;self.history.insert(0,f"{time.strftime('%H:%M:%S')}   {data.code}   {data.final_path.name}");self.toast(f"Saved {data.code}")
                elif kind=="sync":state,msg,queue_count=data;self.server_status.configure(text=msg);self.set_badge(self.server_badge,f"{state} • Q{queue_count}","good" if state=="SERVER ONLINE" else "warn")
                elif kind=="bigseller":self.bigseller_status.configure(text=data)
                elif kind=="error":self.toast(data)
        except queue.Empty:pass
        self.root.after(120,self.event_tick)

    def start_sync_worker(self):
        self.sync_thread=threading.Thread(target=self.sync_worker,daemon=True);self.sync_thread.start()

    def sync_worker(self):
        while not self.sync_stop.is_set():
            try:
                bundles=pending_bundles(self.local_root);server=Path(self.settings.get("server_folder") or "") if self.settings.get("server_folder") else None
                if not server:
                    self.events.put(("sync",("SERVER NOT SET","Configure server folder",len(bundles))))
                elif not server.exists():
                    self.events.put(("sync",("SERVER OFFLINE","Files remain local",len(bundles))))
                elif not self.settings.get("auto_sync",True):
                    self.events.put(("sync",("SYNC OFF","Auto Sync disabled",len(bundles))))
                else:
                    for meta,video,waybill in bundles:
                        if self.sync_stop.is_set():break
                        try:sync_bundle(meta,video,waybill,server)
                        except Exception as exc:self.events.put(("error",f"Sync failed: {exc}"));break
                    q=len(pending_bundles(self.local_root));self.events.put(("sync",("SERVER ONLINE","Verified transfer enabled",q)))
            except Exception as exc:self.events.put(("error",f"Server sync error: {exc}"))
            self.sync_stop.wait(10)

    def sync_now(self):
        self.save_settings();threading.Thread(target=self.one_sync,daemon=True).start()

    def one_sync(self):
        server=Path(self.server_var.get().strip()) if self.server_var.get().strip() else None
        if not server or not server.exists():return self.events.put(("sync",("SERVER OFFLINE","Server not reachable",len(pending_bundles(self.local_root)))))
        for meta,video,waybill in pending_bundles(self.local_root):
            try:sync_bundle(meta,video,waybill,server)
            except Exception as exc:self.events.put(("error",str(exc)));break
        self.events.put(("sync",("SERVER ONLINE","Manual sync complete",len(pending_bundles(self.local_root)))))

    def choose_server(self):
        p=filedialog.askdirectory(title="Choose ScanCode server folder")
        if p:self.server_var.set(p);self.save_settings();self.sync_now()

    def search_server(self):
        q=self.search_var.get().strip().lower();root=Path(self.server_var.get().strip()) if self.server_var.get().strip() else None
        self.search_results.delete(0,"end");self.search_paths=[]
        if not q or not root or not root.exists():return
        for p in root.rglob("*"):
            if p.is_file() and q in p.name.lower() and p.suffix.lower() in {".avi",".mp4",".webm",".png",".json"}:
                self.search_paths.append(p);self.search_results.insert("end",str(p.relative_to(root)))
                if len(self.search_paths)>=100:break

    def open_search_item(self):
        sel=self.search_results.curselection()
        if sel and os.name=="nt":os.startfile(str(self.search_paths[sel[0]]))

    def open_history_item(self):
        sel=self.history.curselection()
        if not sel:return
        text=self.history.get(sel[0]);name=text.split()[-1]
        matches=list(self.local_root.rglob(name))
        if matches and os.name=="nt":os.startfile(str(matches[0]))

    def open_bigseller(self):
        url=self.bigseller_var.get().strip()
        if not url:return self.toast("Enter BigSeller URL first.")
        webbrowser.open(url);self.save_settings()

    def submit_bigseller(self,code):
        pyperclip.copy(code)
        if Desktop is None or send_keys is None:
            return self.events.put(("bigseller",f"Copied {code}; UI Automation unavailable."))
        try:
            wins=[w for w in Desktop(backend="uia").windows() if "bigseller" in (w.window_text() or "").lower() and w.is_visible()]
            if not wins:return self.events.put(("bigseller",f"Copied {code}; open BigSeller first."))
            win=wins[0];win.set_focus();edits=[e for e in win.descendants(control_type="Edit") if e.is_visible() and e.is_enabled()]
            if not edits:return self.events.put(("bigseller",f"Copied {code}; BigSeller input not exposed to Windows UI Automation."))
            edits.sort(key=lambda e:(e.rectangle().left,e.rectangle().top));target=edits[0];target.click_input();send_keys("^a^v{ENTER}",pause=.03)
            self.events.put(("bigseller",f"Submitted {code} to BigSeller input."))
        except Exception as exc:self.events.put(("bigseller",f"Copied {code}; auto-submit failed: {exc}"))

    def end_shift(self):
        pending=len(pending_bundles(self.local_root));server=self.server_var.get().strip();online=bool(server and Path(server).exists())
        rec=len(list(self.local_root.rglob("*.recording.avi")))
        message=f"Server: {'ONLINE' if online else 'OFFLINE / NOT SET'}\nPending bundles: {pending}\nRecovery/in-progress: {rec}"
        if pending==0 and rec==0 and (online or not server):message+="\n\nSHIFT CLEAR"
        else:message+="\n\nNEEDS ATTENTION"
        messagebox.showinfo("End-of-shift verification",message)

    def set_windows_autostart(self,enabled):
        if os.name!="nt" or winreg is None:return
        try:
            key=winreg.OpenKey(winreg.HKEY_CURRENT_USER,r"Software\Microsoft\Windows\CurrentVersion\Run",0,winreg.KEY_SET_VALUE)
            if enabled:
                exe=sys.executable if getattr(sys,"frozen",False) else f'"{sys.executable}" "{Path(__file__).resolve()}"'
                winreg.SetValueEx(key,"ScanCode",0,winreg.REG_SZ,exe)
            else:
                try:winreg.DeleteValue(key,"ScanCode")
                except FileNotFoundError:pass
            winreg.CloseKey(key)
        except Exception:pass

    def on_resize(self,event):
        if event.widget is not self.root:return
        small=event.width<900
        if small and not self.compact_auto:
            self.side.pack_forget();self.bottom.pack_forget();self.compact_auto=True
        elif not small and self.compact_auto:
            self.side.pack(side="right",fill="y",padx=(12,0));self.bottom.pack(fill="x",padx=12,pady=(0,12));self.compact_auto=False

    def toast(self,text):
        self.toast_label.configure(text=text);self.toast_label.place(relx=.5,rely=.94,anchor="center");self.root.after(2800,self.toast_label.place_forget)

    def on_close(self):
        self.save_settings();self.camera_stop.set();self.sync_stop.set()
        with self.sessions_lock:
            sessions=([self.current_session] if self.current_session else [])+self.ending_sessions
            self.current_session=None;self.ending_sessions=[]
        for s in sessions:
            if s:
                try:s.finalize()
                except Exception:pass
        try:
            if self.capture:self.capture.release()
        except Exception:pass
        self.root.destroy()


def main():
    root=tk.Tk()
    ScanCodeApp(root)
    root.mainloop()


if __name__=="__main__":
    main()

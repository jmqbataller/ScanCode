from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
app_path = ROOT / 'native' / 'scancode_app.py'
text = app_path.read_text(encoding='utf-8')


def replace_once(old, new, label):
    global text
    if old not in text:
        raise RuntimeError(f'Patch anchor not found: {label}')
    text = text.replace(old, new, 1)


text = text.replace('APP_VERSION = "4.0.0"', 'APP_VERSION = "4.1.0"', 1)

# Constructor: make services optional for UI smoke tests and simplify shortcuts.
text = text.replace('def __init__(self, root: tk.Tk):', 'def __init__(self, root: tk.Tk, start_services: bool = True):', 1)
text = text.replace('        self.root.geometry("1320x820")\n        self.root.minsize(680, 480)', '        self.root.geometry("1320x820")\n        self.root.minsize(760, 520)', 1)
text = text.replace('        self.compact_auto = False\n', '', 1)
text = text.replace('        self.root.bind("<F1>", lambda e: self.start_resume())\n        self.root.bind("<F2>", lambda e: self.pause_resume())\n        self.root.bind("<F3>", lambda e: self.stop_recording())', '        self.root.bind("<F1>", lambda e: self.start_stop())\n        self.root.bind("<F2>", lambda e: self.pause_resume())', 1)
text = text.replace('        self.start_camera()\n        self.start_sync_worker()\n        self.root.after(25, self.ui_tick)\n        self.root.after(150, self.event_tick)', '        if start_services:\n            self.start_camera()\n            self.start_sync_worker()\n            self.root.after(25, self.ui_tick)\n            self.root.after(150, self.event_tick)\n        else:\n            self.root.after_idle(self._reflow_layout)', 1)

# Replace the full UI shell with a scrollable body and fixed preview area.
start = text.index('    def build_ui(self):')
end = text.index('    def make_badge', start)
new_build_ui = '''    def build_ui(self):
        top = tk.Frame(self.root, bg=PANEL, height=78, highlightbackground=BORDER, highlightthickness=1)
        top.pack(fill="x")
        top.pack_propagate(False)
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

        # The entire workspace below the top bar is one vertically scrollable canvas.
        # This prevents the camera preview from pushing settings/history off-screen.
        shell = tk.Frame(self.root, bg=BG)
        shell.pack(fill="both", expand=True)
        self.body_canvas = tk.Canvas(shell, bg=BG, highlightthickness=0, bd=0)
        self.body_scroll = ttk.Scrollbar(shell, orient="vertical", command=self.body_canvas.yview)
        self.body_canvas.configure(yscrollcommand=self.body_scroll.set)
        self.body_scroll.pack(side="right", fill="y")
        self.body_canvas.pack(side="left", fill="both", expand=True)

        self.content = tk.Frame(self.body_canvas, bg=BG)
        self.content_window = self.body_canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.bind("<Configure>", self._on_content_configure)
        self.body_canvas.bind("<Configure>", self._on_canvas_configure)
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)

        self.main = tk.Frame(self.content, bg=BG)
        self.main.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12,0))
        self.main.grid_columnconfigure(0, weight=1)

        self.left = tk.Frame(self.main, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        self.left.grid(row=0, column=0, sticky="nsew")
        self.side = tk.Frame(self.main, bg=BG, width=330)
        self.side.grid(row=0, column=1, sticky="ns", padx=(12,0))
        self.side.grid_propagate(False)

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

        # Fixed responsive preview box. pack_propagate(False) is the key: the
        # ImageTk frame can no longer grow the whole application vertically.
        self.video_border = tk.Frame(self.left, bg=BORDER, height=440, padx=2, pady=2)
        self.video_border.pack(fill="x", padx=8)
        self.video_border.pack_propagate(False)
        self.video_label = tk.Label(self.video_border, bg="#000000", fg=TEXT, text="Starting native camera…", font=("Segoe UI", 12, "bold"))
        self.video_label.pack(fill="both", expand=True)

        transport = tk.Frame(self.left, bg=PANEL); transport.pack(fill="x", padx=16, pady=10)
        self.start_stop_btn = self.button(transport, "Start", self.start_stop, True)
        self.start_stop_btn.pack(side="left", padx=(0,8))
        self.pause_resume_btn = self.button(transport, "Pause", self.pause_resume)
        self.pause_resume_btn.pack(side="left")
        self.transport_status = self.label(transport, "Waiting for scan", 9, True, MUTED)
        self.transport_status.pack(side="right")
        self.update_transport_controls()

        manual = tk.Frame(self.left, bg=PANEL); manual.pack(fill="x", padx=16, pady=(0,14))
        self.manual_var = tk.StringVar()
        manual_entry = tk.Entry(manual, textvariable=self.manual_var, bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat", font=("Segoe UI",10))
        manual_entry.pack(side="left", fill="x", expand=True, ipady=8)
        manual_entry.bind("<Return>", lambda e: self.manual_scan())
        self.button(manual, "Simulate Scan", self.manual_scan, True).pack(side="left", padx=(8,0))

        self.build_side()
        self.build_history_search()
        self.toast_label = tk.Label(self.root, text="", bg="#1d1d22", fg=TEXT, padx=14, pady=8, font=("Segoe UI",9,"bold"))

        self.root.after_idle(self._reflow_layout)

    def _on_content_configure(self, event=None):
        self.body_canvas.configure(scrollregion=self.body_canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.body_canvas.itemconfigure(self.content_window, width=max(1, event.width))
        self.root.after_idle(self._reflow_layout)

    def _on_mousewheel(self, event):
        try:
            delta = -1 if event.delta > 0 else 1
            self.body_canvas.yview_scroll(delta * 3, "units")
        except Exception:
            pass

    def _reflow_layout(self):
        if not hasattr(self, "main"):
            return
        width = max(1, self.body_canvas.winfo_width())
        narrow = width < 980

        if narrow:
            self.side.grid_configure(row=1, column=0, sticky="ew", padx=0, pady=(12,0))
            self.side.configure(width=1)
            self.side.grid_propagate(True)
            self.main.grid_columnconfigure(1, weight=0, minsize=0)
            if hasattr(self, "history_panel"):
                self.history_panel.grid_configure(row=0, column=0, sticky="nsew", padx=0, pady=(0,10))
                self.search_panel.grid_configure(row=1, column=0, sticky="nsew", padx=0)
                self.bottom.grid_columnconfigure(0, weight=1)
                self.bottom.grid_columnconfigure(1, weight=0, minsize=0)
        else:
            self.side.grid_configure(row=0, column=1, sticky="ns", padx=(12,0), pady=0)
            self.side.configure(width=330)
            self.side.grid_propagate(False)
            self.main.grid_columnconfigure(1, weight=0, minsize=330)
            if hasattr(self, "history_panel"):
                self.history_panel.grid_configure(row=0, column=0, sticky="nsew", padx=(0,10), pady=0)
                self.search_panel.grid_configure(row=0, column=1, sticky="nsew", padx=0, pady=0)
                self.bottom.grid_columnconfigure(0, weight=1)
                self.bottom.grid_columnconfigure(1, weight=1, minsize=360)

        # Keep camera preview usable but bounded. It will never expand beyond 500px.
        left_width = self.left.winfo_width() if self.left.winfo_width() > 100 else max(640, width - (360 if not narrow else 24))
        preview_h = int(max(280, min(500, left_width * 9 / 16)))
        self.video_border.configure(height=preview_h)
        self._on_content_configure()

'''
text = text[:start] + new_build_ui + text[end:]

# Replace history/search so it belongs to the scrollable body instead of root.
start = text.index('    def build_history_search(self):')
end = text.index('    def entry_row', start)
new_history = '''    def build_history_search(self):
        bottom = tk.Frame(self.content, bg=BG)
        bottom.grid(row=1, column=0, sticky="ew", padx=12, pady=12)
        self.bottom = bottom
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_columnconfigure(1, weight=1, minsize=360)

        hist = tk.Frame(bottom, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        hist.grid(row=0, column=0, sticky="nsew", padx=(0,10))
        self.history_panel = hist
        self.label(hist, "Session History", 11, True).pack(anchor="w", padx=12, pady=(8,4))
        self.history = tk.Listbox(hist, bg="#0c0c0f", fg=TEXT, selectbackground=RED, relief="flat", height=7)
        self.history.pack(fill="both", expand=True, padx=10, pady=(0,10))
        self.history.bind("<Double-Button-1>", lambda e: self.open_history_item())

        search = tk.Frame(bottom, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        search.grid(row=0, column=1, sticky="nsew")
        self.search_panel = search
        self.label(search, "Server Parcel Search", 11, True).pack(anchor="w", padx=12, pady=(8,4))
        sr = tk.Frame(search, bg=PANEL); sr.pack(fill="x", padx=10)
        self.search_var = tk.StringVar()
        tk.Entry(sr, textvariable=self.search_var, bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat").pack(side="left", fill="x", expand=True, ipady=5)
        self.button(sr, "Search", self.search_server, True).pack(side="left", padx=(6,0))
        self.search_results = tk.Listbox(search, bg="#0c0c0f", fg=TEXT, selectbackground=RED, relief="flat", height=7)
        self.search_results.pack(fill="both", expand=True, padx=10, pady=8)
        self.search_results.bind("<Double-Button-1>", lambda e: self.open_search_item())
        self.search_paths = []

'''
text = text[:start] + new_history + text[end:]

# Recording controls: one Start/Stop button + one Pause/Resume button.
pattern = re.compile(r'    def start_resume\(self\):[\s\S]*?    def finalize_session\(self,s\):', re.M)
replacement = '''    def update_transport_controls(self):
        if not hasattr(self, "start_stop_btn"):
            return
        session = self.current_session
        if session:
            self.start_stop_btn.configure(text="Stop", bg=RED, activebackground=DARK_RED, state="normal")
            self.pause_resume_btn.configure(
                text="Resume" if session.paused else "Pause",
                state="normal",
                bg=PANEL2,
                activebackground="#24242b",
            )
        else:
            self.start_stop_btn.configure(text="Start", bg=RED, activebackground=DARK_RED, state="normal")
            self.pause_resume_btn.configure(text="Pause", state="disabled", disabledforeground=MUTED)

    def start_stop(self):
        if self.current_session:
            return self.stop_recording()
        code = self.manual_var.get().strip() or f"MANUAL-{int(time.time())}"
        self.accept_scan(code)

    # Backwards-compatible alias for older internal calls / shortcuts.
    def start_resume(self):
        self.start_stop()

    def pause_resume(self):
        if not self.current_session:
            return self.toast("No active recording.")
        self.current_session.paused = not self.current_session.paused
        if self.current_session.paused:
            self.set_badge(self.record_badge, "PAUSED", "warn")
            self.transport_status.configure(text=f"Paused • {self.current_session.code}", fg=AMBER)
        else:
            self.set_badge(self.record_badge, "● RECORDING", "bad")
            self.transport_status.configure(text=f"Recording • {self.current_session.code}", fg=TEXT)
        self.update_transport_controls()

    def stop_recording(self):
        with self.sessions_lock:
            if not self.current_session:
                return self.toast("No active recording.")
            s = self.current_session
            self.current_session = None
            s.stop_at = time.time()
            self.ending_sessions.append(s)
        self.current_code.configure(text="Waiting for scan")
        self.detail_status.configure(text="IDLE", fg=MUTED)
        self.transport_status.configure(text="Waiting for scan", fg=MUTED)
        self.video_border.configure(bg=BORDER)
        self.set_badge(self.record_badge, "NOT RECORDING", "neutral")
        self.update_transport_controls()

    def finalize_session(self,s):'''
text, n = pattern.subn(replacement, text, count=1)
if n != 1:
    raise RuntimeError('Could not replace recording controls')

# Ensure auto-started scans update the two-button state.
old = '        self.current_code.configure(text=code);self.detail_status.configure(text="RECORDING",fg=RED);self.transport_status.configure(text=f"Recording • {code}",fg=TEXT);self.video_border.configure(bg=RED);self.set_badge(self.record_badge,"● RECORDING","bad")'
new = '        self.current_code.configure(text=code);self.detail_status.configure(text="RECORDING",fg=RED);self.transport_status.configure(text=f"Recording • {code}",fg=TEXT);self.video_border.configure(bg=RED);self.set_badge(self.record_badge,"● RECORDING","bad");self.update_transport_controls()'
replace_once(old, new, 'scan starts transport state')

# Replace resize behavior: never hide controls; only reflow and resize the preview.
start = text.index('    def on_resize(self,event):')
end = text.index('    def toast', start)
new_resize = '''    def on_resize(self,event):
        if event.widget is not self.root:
            return
        if getattr(self, "_resize_after", None):
            try:
                self.root.after_cancel(self._resize_after)
            except Exception:
                pass
        self._resize_after = self.root.after(80, self._reflow_layout)

'''
text = text[:start] + new_resize + text[end:]

# Update title/version in any remaining literal text.
text = text.replace('v4.0.0', 'v4.1.0')
app_path.write_text(text, encoding='utf-8')

# Add a UI smoke test that validates scrollability, responsive stacking and control states.
test_path = ROOT / 'native' / 'test_ui_layout.py'
test_path.write_text(r'''import tkinter as tk
from types import SimpleNamespace

from scancode_app import ScanCodeApp


def main():
    root = tk.Tk()
    root.geometry('1200x760')
    app = ScanCodeApp(root, start_services=False)
    root.update_idletasks()
    root.update()

    assert hasattr(app, 'body_canvas') and hasattr(app, 'body_scroll')
    assert app.start_stop_btn.cget('text') == 'Start'
    assert app.pause_resume_btn.cget('state') == 'disabled'
    assert app.video_border.winfo_height() <= 505

    # Simulate a live recording to test Start/Stop and Pause/Resume button states.
    dummy = SimpleNamespace(code='QA-001', paused=False, stop_at=None)
    app.current_session = dummy
    app.update_transport_controls()
    assert app.start_stop_btn.cget('text') == 'Stop'
    assert app.pause_resume_btn.cget('text') == 'Pause'
    assert app.pause_resume_btn.cget('state') == 'normal'
    app.pause_resume()
    assert dummy.paused is True
    assert app.pause_resume_btn.cget('text') == 'Resume'

    # Narrow window must stack, not hide, the side panel and search panel.
    root.geometry('800x600')
    root.update_idletasks(); root.update()
    app._reflow_layout(); root.update_idletasks()
    assert app.side.winfo_ismapped()
    assert int(app.side.grid_info()['row']) == 1
    assert app.search_panel.winfo_ismapped()
    assert int(app.search_panel.grid_info()['row']) == 1
    assert app.video_border.winfo_height() <= 505

    # Content must expose a scroll region larger than the viewport on compact height.
    bbox = app.body_canvas.bbox('all')
    assert bbox is not None and bbox[3] > app.body_canvas.winfo_height()

    # Restore dummy state without finalization work and exit cleanly.
    app.current_session = None
    app.ending_sessions = []
    app.camera_stop.set(); app.sync_stop.set()
    root.destroy()
    print('UI PASS: fixed camera preview, scrollable workspace, responsive stacking, Start/Stop + Pause/Resume states')


if __name__ == '__main__':
    main()
''', encoding='utf-8')

print('Applied ScanCode native v4.1 UI/control stabilization patch.')

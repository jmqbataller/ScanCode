from __future__ import annotations

import json
import time
import tkinter as tk
from tkinter import ttk

import cv2
from PIL import Image, ImageTk

import scancode_app as base_app
import scancode_app_v44 as v44
import scancode_app_v45 as v45
from scancode_core import zoom_crop
from scancode_enhanced_v46 import read_codes_optimized

APP_VERSION = "4.6.0"
base_app.APP_VERSION = APP_VERSION
v44.APP_VERSION = APP_VERSION
v45.APP_VERSION = APP_VERSION
base_app.read_codes = read_codes_optimized

FOCUS_ZOOM = {
    "Near": 1.35,
    "Far": 2.15,
}


class ScanCodeApp(v45.ScanCodeApp):
    """v4.6: lighter scanner + autofocus option + Near/Far waybill focus."""

    def __init__(self, root: tk.Tk, start_services: bool = True):
        # These must exist before the inherited UI is built.
        self.autofocus_var = tk.BooleanVar(master=root, value=False)
        self.waybill_focus_var = tk.BooleanVar(master=root, value=True)
        self.waybill_focus_mode_var = tk.StringVar(master=root, value="Near")
        super().__init__(root, start_services=start_services)

    def defaults(self):
        data = super().defaults()
        manual = float(data.get("scanner_zoom", 1.85) or 1.85)
        data.update({
            "barcode_filter": "QR + Barcode",
            "camera_autofocus": False,
            "waybill_focus": True,
            "waybill_focus_mode": "Near",
            "manual_scanner_zoom": manual,
        })
        data["scanner_zoom"] = FOCUS_ZOOM["Near"]
        return data

    def load_settings(self):
        data = super().load_settings()

        old_filter = str(data.get("barcode_filter") or "shipping").strip().lower()
        if old_filter in {"qr", "qr only"}:
            data["barcode_filter"] = "QR only"
        else:
            data["barcode_filter"] = "QR + Barcode"

        data.setdefault("camera_autofocus", False)
        data.setdefault("waybill_focus", True)
        data.setdefault("waybill_focus_mode", "Near")
        data.setdefault("manual_scanner_zoom", float(data.get("scanner_zoom", 1.85) or 1.85))

        if data.get("waybill_focus", True):
            mode = data.get("waybill_focus_mode", "Near")
            if mode not in FOCUS_ZOOM:
                mode = "Near"
            data["waybill_focus_mode"] = mode
            data["scanner_zoom"] = FOCUS_ZOOM[mode]
        else:
            data["scanner_zoom"] = float(data.get("manual_scanner_zoom", 1.85) or 1.85)
        return data

    def save_settings(self):
        # Preserve the manual slider even while a Near/Far preset is active.
        try:
            manual_zoom = float(self.scanner_zoom_var.get() or 1.85)
        except Exception:
            manual_zoom = 1.85

        super().save_settings()

        self.settings["barcode_filter"] = self.filter_var.get() or "QR + Barcode"
        self.settings["camera_autofocus"] = bool(self.autofocus_var.get())
        self.settings["waybill_focus"] = bool(self.waybill_focus_var.get())
        mode = self.waybill_focus_mode_var.get() or "Near"
        if mode not in FOCUS_ZOOM:
            mode = "Near"
        self.settings["waybill_focus_mode"] = mode

        # Only overwrite the saved manual value when the preset is disabled.
        if not self.settings["waybill_focus"]:
            self.settings["manual_scanner_zoom"] = manual_zoom
        else:
            self.settings.setdefault("manual_scanner_zoom", manual_zoom)

        if self.settings["waybill_focus"]:
            self.settings["scanner_zoom"] = FOCUS_ZOOM[mode]
        else:
            self.settings["scanner_zoom"] = float(self.settings.get("manual_scanner_zoom", manual_zoom) or manual_zoom)

        try:
            self.settings_path.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except Exception:
            pass

    def combo_row(self, parent, label, variable, values):
        if label == "Barcode filter":
            # Friendly default: scan QR plus normal shipping barcodes.
            super().combo_row(parent, "Scan formats", variable, ["QR + Barcode", "QR only"])

            self.check(parent, "Enable camera autofocus (if supported)", self.autofocus_var)
            self.check(parent, "Enable Waybill Focus", self.waybill_focus_var)

            row = tk.Frame(parent, bg=base_app.PANEL)
            row.pack(fill="x", padx=14, pady=3)
            self.label(row, "Waybill distance", 8, False, base_app.MUTED).pack(anchor="w")
            combo = ttk.Combobox(
                row,
                textvariable=self.waybill_focus_mode_var,
                state="readonly",
                values=["Near", "Far"],
            )
            combo.pack(fill="x")
            combo.bind("<<ComboboxSelected>>", lambda e: self._focus_setting_changed())

            tk.Label(
                parent,
                text=(
                    "Near = wider scan area for a close/large waybill.  "
                    "Far = tighter center zoom for a smaller waybill.  "
                    "Disable Waybill Focus to use the manual scanner zoom slider."
                ),
                bg=base_app.PANEL,
                fg=base_app.MUTED,
                font=("Segoe UI", 8),
                wraplength=285,
                justify="left",
            ).pack(anchor="w", padx=14, pady=(3, 5))
            return
        return super().combo_row(parent, label, variable, values)

    def _focus_setting_changed(self):
        self.save_settings()
        mode = self.settings.get("waybill_focus_mode", "Near")
        self.toast(f"Waybill Focus: {mode}.")

    def apply_settings_to_ui(self):
        super().apply_settings_to_ui()
        self.filter_var.set(self.settings.get("barcode_filter", "QR + Barcode"))
        self.autofocus_var.set(bool(self.settings.get("camera_autofocus", False)))
        self.waybill_focus_var.set(bool(self.settings.get("waybill_focus", True)))
        self.waybill_focus_mode_var.set(self.settings.get("waybill_focus_mode", "Near"))

        # The visible slider always represents the user's manual fallback value.
        if self.settings.get("waybill_focus", True):
            self.scanner_zoom_var.set(float(self.settings.get("manual_scanner_zoom", 1.85) or 1.85))

    def open_capture(self, mode, camera_index=0, network_url=""):
        if mode == "Phone / Network Camera":
            return super().open_capture(mode, camera_index, network_url)

        try:
            preferred = max(0, min(5, int(camera_index)))
        except Exception:
            preferred = 0

        autofocus_requested = bool(self.settings.get("camera_autofocus", False))
        indexes = [preferred] + [i for i in range(6) if i != preferred]
        backends = [
            ("DirectShow", cv2.CAP_DSHOW),
            ("Media Foundation", cv2.CAP_MSMF),
            ("Windows Auto", cv2.CAP_ANY),
        ]
        resolutions = [(1920, 1080), (1280, 720)]

        for idx in indexes:
            for backend_name, backend in backends:
                for width, height in resolutions:
                    if self.camera_stop.is_set():
                        raise RuntimeError("Camera start cancelled.")
                    cap = None
                    try:
                        cap = cv2.VideoCapture(idx, backend)
                        try:
                            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                        except Exception:
                            pass
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                        cap.set(cv2.CAP_PROP_FPS, 30)

                        try:
                            cap.set(cv2.CAP_PROP_AUTOFOCUS, 1 if autofocus_requested else 0)
                        except Exception:
                            pass

                        if not cap.isOpened():
                            cap.release()
                            continue

                        deadline = time.time() + 1.5
                        while time.time() < deadline and not self.camera_stop.is_set():
                            ok, frame = cap.read()
                            if ok and frame is not None and getattr(frame, "size", 0):
                                actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or frame.shape[1])
                                actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or frame.shape[0])
                                focus_text = "AF requested" if autofocus_requested else "fixed-focus"
                                self.active_camera_index = idx
                                self.active_camera_backend = f"{backend_name} {actual_w}x{actual_h} {focus_text}"
                                return cap
                            time.sleep(0.055)
                    except Exception:
                        pass
                    finally:
                        if cap is not None:
                            if self.active_camera_index != idx or not cap.isOpened():
                                try:
                                    cap.release()
                                except Exception:
                                    pass

        raise RuntimeError(
            "No working PC/USB camera was detected. Tried Camera 0–5 at "
            "1920x1080 and 1280x720 with Windows camera backends."
        )

    def ui_tick(self):
        # ~22 FPS preview instead of ~33 FPS. Camera capture/recording stays at
        # full requested FPS; this only reduces Tk/Pillow preview CPU usage.
        with self.frame_lock:
            frame = None if self.latest_frame is None else self.latest_frame.copy()
        if frame is not None:
            far = zoom_crop(frame, float(self.far_zoom_var.get() or 1))
            rgb = cv2.cvtColor(far, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            vw = max(320, self.video_label.winfo_width())
            vh = max(220, self.video_label.winfo_height())
            img.thumbnail((vw, vh), Image.Resampling.LANCZOS)
            self.preview_photo = ImageTk.PhotoImage(img)
            self.video_label.configure(image=self.preview_photo, text="")
        self.root.after(45, self.ui_tick)


def main():
    root = tk.Tk()
    ScanCodeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

from __future__ import annotations

import threading
import time
import tkinter as tk

import cv2

import scancode_app as base
from scancode_core import camera_quality, read_codes, zoom_crop


# Keep the stable v4.2 warehouse workflow/UI, but replace only the camera runtime
# with the v4.3 startup implementation used by the packaged Windows EXE.
base.APP_VERSION = "4.3.0"
ScanCodeApp = base.ScanCodeApp


def start_camera(self):
    """Start the camera only after Tk's UI loop is alive.

    All tkinter values are captured on the UI thread before the native worker is
    created. This avoids frozen-EXE startup races caused by reading Tk variables
    from a background thread.
    """
    if self.camera_thread and self.camera_thread.is_alive():
        if self.camera_stop.is_set():
            self.root.after(250, self.start_camera)
        return

    mode = self.mode_var.get() or "PC / USB Camera"
    try:
        camera_index = int(self.camera_var.get() or self.settings.get("camera_index", 0) or 0)
    except Exception:
        camera_index = 0
    network_url = self.network_var.get().strip()

    self.camera_stop.clear()
    self.camera_live = False
    self.set_badge(self.camera_badge, "CAMERA STARTING", "warn")
    self.video_label.configure(text="Detecting camera…", image="")
    self.camera_thread = threading.Thread(
        target=self.camera_worker,
        args=(mode, camera_index, network_url),
        daemon=True,
    )
    self.camera_thread.start()


def open_capture(self, mode, camera_index=0, network_url=""):
    """Open the requested camera, automatically falling back to any local webcam."""
    if mode == "Phone / Network Camera":
        url = str(network_url or "").strip()
        if not url:
            raise RuntimeError("Network camera URL is empty.")
        cap = cv2.VideoCapture(url)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError("Could not open network camera URL.")
        self.v43_active_camera_index = None
        self.v43_active_camera_backend = "Network"
        return cap

    try:
        preferred = max(0, min(5, int(camera_index)))
    except Exception:
        preferred = 0

    # The selected/saved camera is preferred. If Windows changed camera indexes
    # after install/driver changes, ScanCode automatically probes Camera 0-5.
    indexes = [preferred] + [i for i in range(6) if i != preferred]
    backends = [
        ("DirectShow", cv2.CAP_DSHOW),
        ("Media Foundation", cv2.CAP_MSMF),
        ("Windows Auto", cv2.CAP_ANY),
    ]

    for idx in indexes:
        for backend_name, backend in backends:
            if self.camera_stop.is_set():
                raise RuntimeError("Camera start cancelled.")

            cap = None
            success = False
            try:
                cap = cv2.VideoCapture(idx, backend)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                cap.set(cv2.CAP_PROP_FPS, 30)
                try:
                    cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
                except Exception:
                    pass

                if not cap.isOpened():
                    continue

                # Some Windows backends say "opened" before a real frame is
                # available. Warm up for a short period before accepting it.
                deadline = time.time() + 1.25
                while time.time() < deadline and not self.camera_stop.is_set():
                    ok, frame = cap.read()
                    if ok and frame is not None and getattr(frame, "size", 0):
                        self.v43_active_camera_index = idx
                        self.v43_active_camera_backend = backend_name
                        success = True
                        return cap
                    time.sleep(0.06)
            except Exception:
                pass
            finally:
                if cap is not None and not success:
                    try:
                        cap.release()
                    except Exception:
                        pass

    raise RuntimeError(
        "No working PC/USB camera was detected. ScanCode tried Camera 0-5 using "
        "DirectShow, Media Foundation and Windows Auto. Close Windows Camera, "
        "Teams, Zoom, OBS or Discord if one of them is using the webcam, then "
        "press Restart Camera."
    )


def camera_worker(self, mode, camera_index, network_url):
    """Native capture loop with thread-safe settings access and auto reconnect."""
    retry = 0
    while not self.camera_stop.is_set():
        try:
            self.v43_active_camera_index = None
            self.v43_active_camera_backend = ""
            self.capture = self.open_capture(mode, camera_index, network_url)
            self.camera_live = True
            self.events.put(("camera_live", None))
            retry = 0

            fps = float(self.capture.get(cv2.CAP_PROP_FPS) or 25)
            fps = fps if 5 <= fps <= 60 else 25
            frame_no = 0

            while not self.camera_stop.is_set():
                ok, frame = self.capture.read()
                if not ok or frame is None:
                    raise RuntimeError("Camera stopped returning frames.")

                self.last_frame_at = time.time()
                frame_no += 1
                with self.frame_lock:
                    self.latest_frame = frame.copy()

                # Never touch tkinter variables from this worker thread.
                far_zoom = float(self.settings.get("far_zoom", 1.0) or 1.0)
                scanner_zoom = float(self.settings.get("scanner_zoom", 1.75) or 1.75)
                barcode_filter = str(self.settings.get("barcode_filter", "shipping") or "shipping")
                quality_enabled = bool(self.settings.get("quality", True))

                far = zoom_crop(frame, far_zoom)
                self.write_sessions(far, fps)
                if frame_no % 3 == 0:
                    for code, fmt in read_codes(frame, barcode_filter, scanner_zoom):
                        self.events.put(("barcode", (code, fmt)))
                if quality_enabled and frame_no % 30 == 0:
                    self.events.put(("quality", camera_quality(frame)))
            break
        except Exception as exc:
            self.camera_live = False
            self.events.put(("camera_error", str(exc)))
            retry += 1
            try:
                if self.capture:
                    self.capture.release()
            except Exception:
                pass
            self.capture = None
            if self.camera_stop.wait(min(6, 1 + retry)):
                break


# Replace only the camera runtime. Existing scanner, recording, sync, BigSeller,
# Start/Pause/Stop and evidence behavior stays on the proven v4.2 code path.
ScanCodeApp.start_camera = start_camera
ScanCodeApp.open_capture = open_capture
ScanCodeApp.camera_worker = camera_worker


def main():
    root = tk.Tk()

    # Build the entire UI first without starting camera/background services.
    # Once Tk has entered its event queue, automatically open the camera.
    app = ScanCodeApp(root, start_services=False)
    app.start_sync_worker()
    root.after(25, app.ui_tick)
    root.after(150, app.event_tick)
    root.after(300, app.start_camera)
    root.mainloop()


if __name__ == "__main__":
    main()

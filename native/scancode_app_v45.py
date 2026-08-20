from __future__ import annotations

import time
import tkinter as tk

import cv2

import scancode_app as base_app
import scancode_app_v44 as v44
from scancode_enhanced import read_codes_enhanced

APP_VERSION = "4.5.0"
base_app.APP_VERSION = APP_VERSION
v44.APP_VERSION = APP_VERSION

# Keep the stable v4.3/v4.4 camera worker and parcel workflow, but replace the
# decoder it calls with the fixed-focus enhancement pipeline.
base_app.read_codes = read_codes_enhanced


class ScanCodeApp(v44.ScanCodeApp):
    """v4.5: Active App output + 1080p fixed-focus QR/barcode enhancement."""

    def defaults(self):
        data = super().defaults()
        # A slightly tighter scanner crop helps a fixed-focus 1080p webcam use
        # more pixels on the parcel label without changing the recording view.
        if float(data.get("scanner_zoom", 1.75) or 1.75) < 1.85:
            data["scanner_zoom"] = 1.85
        return data

    def open_capture(self, mode, camera_index=0, network_url=""):
        if mode == "Phone / Network Camera":
            return super().open_capture(mode, camera_index, network_url)

        try:
            preferred = max(0, min(5, int(camera_index)))
        except Exception:
            preferred = 0

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

                        # A4Tech and many 1080p USB webcams expose their best
                        # 1080p/30 path through MJPG, especially via DirectShow.
                        try:
                            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                        except Exception:
                            pass
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                        cap.set(cv2.CAP_PROP_FPS, 30)

                        # This profile is specifically designed for fixed-focus
                        # cameras. Do not rely on unsupported autofocus controls.
                        try:
                            cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
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
                                self.active_camera_index = idx
                                self.active_camera_backend = f"{backend_name} {actual_w}x{actual_h} fixed-focus"
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
            "1920x1080 and 1280x720 using DirectShow, Media Foundation and "
            "Windows Auto. Close other apps using the webcam, then Restart Camera."
        )


def main():
    root = tk.Tk()
    ScanCodeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

import queue
import threading

import numpy as np

import scancode_app


class FakeCapture:
    def __init__(self, source, backend=None):
        self.source = source
        self.backend = backend
        self.released = False
        self._opened = source == 2 and backend == scancode_app.cv2.CAP_MSMF

    def set(self, *_args):
        return True

    def isOpened(self):
        return self._opened and not self.released

    def read(self):
        if not self.isOpened():
            return False, None
        return True, np.zeros((720, 1280, 3), dtype=np.uint8)

    def release(self):
        self.released = True


def run():
    original = scancode_app.cv2.VideoCapture
    calls = []

    def fake_video_capture(source, backend=None):
        calls.append((source, backend))
        return FakeCapture(source, backend)

    scancode_app.cv2.VideoCapture = fake_video_capture
    try:
        app = scancode_app.ScanCodeApp.__new__(scancode_app.ScanCodeApp)
        app.camera_stop = threading.Event()
        app.capture = None
        app.active_camera_index = None
        app.active_camera_backend = ""
        app.events = queue.Queue()

        cap = app.open_capture("PC / USB Camera", camera_index=0, network_url="")

        assert cap.isOpened(), "Expected fallback camera to open"
        assert app.active_camera_index == 2, app.active_camera_index
        assert app.active_camera_backend == "Media Foundation", app.active_camera_backend
        assert calls[0] == (0, scancode_app.cv2.CAP_DSHOW), calls[:3]
        assert (2, scancode_app.cv2.CAP_MSMF) in calls, calls
        print("PASS: saved Camera 0 failed; ScanCode auto-detected Camera 2 via Media Foundation.")
    finally:
        scancode_app.cv2.VideoCapture = original


if __name__ == "__main__":
    run()

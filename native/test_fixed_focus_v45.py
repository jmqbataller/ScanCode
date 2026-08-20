import threading

import cv2
import numpy as np
import qrcode

import scancode_app_v45 as appmod
from scancode_enhanced import read_codes_enhanced


def build_soft_qr(payload: str):
    qr = qrcode.QRCode(version=None, box_size=8, border=4)
    qr.add_data(payload)
    qr.make(fit=True)
    pil = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    image = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)

    # Simulate a fixed-focus webcam: reduced contrast + mild optical softness.
    image = cv2.resize(image, (250, 250), interpolation=cv2.INTER_AREA)
    image = cv2.GaussianBlur(image, (5, 5), 1.05)
    image = cv2.addWeighted(image, 0.58, np.full_like(image, 205), 0.42, 0)

    canvas = np.full((1080, 1920, 3), 220, dtype=np.uint8)
    y = (1080 - image.shape[0]) // 2
    x = (1920 - image.shape[1]) // 2
    canvas[y:y + image.shape[0], x:x + image.shape[1]] = image
    return canvas


class FakeCapture:
    instances = []

    def __init__(self, source, backend=None):
        self.source = source
        self.backend = backend
        self.props = {}
        self.released = False
        FakeCapture.instances.append(self)

    def set(self, prop, value):
        self.props[prop] = value
        return True

    def get(self, prop):
        return self.props.get(prop, 30 if prop == cv2.CAP_PROP_FPS else 0)

    def isOpened(self):
        return not self.released and self.source == 0

    def read(self):
        if not self.isOpened():
            return False, None
        w = int(self.props.get(cv2.CAP_PROP_FRAME_WIDTH, 1920))
        h = int(self.props.get(cv2.CAP_PROP_FRAME_HEIGHT, 1080))
        return True, np.full((h, w, 3), 128, dtype=np.uint8)

    def release(self):
        self.released = True


def main():
    payload = "SCANCODE-V45-FIXED-FOCUS-QR-001"
    frame = build_soft_qr(payload)
    found = read_codes_enhanced(frame, "all", 1.85)
    assert any(text == payload for text, _fmt in found), found

    original_capture = appmod.cv2.VideoCapture
    try:
        FakeCapture.instances.clear()
        appmod.cv2.VideoCapture = FakeCapture

        app = appmod.ScanCodeApp.__new__(appmod.ScanCodeApp)
        app.camera_stop = threading.Event()
        app.active_camera_index = None
        app.active_camera_backend = ""

        cap = app.open_capture("PC / USB Camera", 0, "")
        assert cap is not None and cap.isOpened()
        assert app.active_camera_index == 0
        assert "1920x1080" in app.active_camera_backend, app.active_camera_backend
        assert cap.props.get(cv2.CAP_PROP_FRAME_WIDTH) == 1920
        assert cap.props.get(cv2.CAP_PROP_FRAME_HEIGHT) == 1080
        assert cap.props.get(cv2.CAP_PROP_FPS) == 30
        assert cap.props.get(cv2.CAP_PROP_AUTOFOCUS) == 0
        assert cv2.CAP_PROP_FOURCC in cap.props
        cap.release()
    finally:
        appmod.cv2.VideoCapture = original_capture

    print("FIXED FOCUS V4.5 PASS: softened QR decoded; 1080p MJPG fixed-focus capture requested.")


if __name__ == "__main__":
    main()

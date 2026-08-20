import threading

import cv2
import numpy as np
import qrcode

import scancode_app_v46 as appmod
import scancode_enhanced_v46 as decmod


class FakeBarcode:
    def __init__(self, text, fmt):
        self.text = text
        self.format = f"BarcodeFormat.{fmt}"


def build_soft_qr(payload: str):
    qr = qrcode.QRCode(version=None, box_size=8, border=4)
    qr.add_data(payload)
    qr.make(fit=True)
    pil = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    image = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
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
    # Real softened QR regression through the lighter progressive decoder.
    payload = "SCANCODE-V46-LIGHT-QR-001"
    frame = build_soft_qr(payload)
    found = []
    for _ in range(4):
        found = decmod.read_codes_optimized(frame, "QR + Barcode", 1.35)
        if found:
            break
    assert any(text == payload for text, _fmt in found), found

    # Prove that normal 1D barcodes are not filtered out by the new default.
    original_reader = decmod.zxingcpp.read_barcodes
    try:
        decmod.zxingcpp.read_barcodes = lambda *a, **k: [
            FakeBarcode("SPX123456789", "Code128"),
            FakeBarcode("QR-TEST", "QRCode"),
        ]
        sample = np.full((80, 160), 255, dtype=np.uint8)
        both = decmod._decode_once(sample, "QR + Barcode")
        assert ("SPX123456789", "Code128") in both, both
        assert ("QR-TEST", "QRCode") in both, both
        qr_only = decmod._decode_once(sample, "QR only")
        assert ("SPX123456789", "Code128") not in qr_only, qr_only
        assert ("QR-TEST", "QRCode") in qr_only, qr_only
    finally:
        decmod.zxingcpp.read_barcodes = original_reader

    # Near/Far are real scan presets, not labels only.
    assert appmod.FOCUS_ZOOM["Near"] < appmod.FOCUS_ZOOM["Far"]

    # Autofocus option must reach the OpenCV capture property when enabled.
    original_capture = appmod.cv2.VideoCapture
    try:
        FakeCapture.instances.clear()
        appmod.cv2.VideoCapture = FakeCapture
        app = appmod.ScanCodeApp.__new__(appmod.ScanCodeApp)
        app.camera_stop = threading.Event()
        app.active_camera_index = None
        app.active_camera_backend = ""
        app.settings = {"camera_autofocus": True}

        cap = app.open_capture("PC / USB Camera", 0, "")
        assert cap is not None and cap.isOpened()
        assert cap.props.get(cv2.CAP_PROP_AUTOFOCUS) == 1
        assert cap.props.get(cv2.CAP_PROP_FRAME_WIDTH) == 1920
        assert cap.props.get(cv2.CAP_PROP_FRAME_HEIGHT) == 1080
        assert "AF requested" in app.active_camera_backend
        cap.release()
    finally:
        appmod.cv2.VideoCapture = original_capture

    defaults = appmod.ScanCodeApp.__new__(appmod.ScanCodeApp).defaults()
    assert defaults["barcode_filter"] == "QR + Barcode"
    assert defaults["waybill_focus"] is True
    assert defaults["camera_autofocus"] is False

    print("V4.6 PASS: light decoder, QR + Code128, Near/Far focus and optional autofocus verified.")


if __name__ == "__main__":
    main()

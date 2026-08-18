import json
import tempfile
from pathlib import Path

import cv2
import numpy as np
import qrcode

from scancode_core import ParcelSession, camera_quality, pending_bundles, read_codes, sync_bundle, waybill_crop


def make_qr(text="SCANCODE-TEST-001"):
    img = qrcode.make(text).convert("RGB")
    arr = np.array(img)
    arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    canvas = np.full((720, 1280, 3), 230, dtype=np.uint8)
    h, w = arr.shape[:2]
    scale = min(360 / w, 360 / h)
    arr = cv2.resize(arr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_NEAREST)
    h, w = arr.shape[:2]
    y, x = (720 - h) // 2, (1280 - w) // 2
    canvas[y:y+h, x:x+w] = arr
    return canvas


def main():
    frame = make_qr()
    codes = read_codes(frame, "all", 1.0)
    assert any(c[0] == "SCANCODE-TEST-001" for c in codes), codes

    state, brightness, focus = camera_quality(frame)
    assert brightness > 0
    crop = waybill_crop(frame, 1.2)
    assert crop is not None and crop.size > 0

    with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as sd:
        local = Path(td) / "2026-08-18"
        local.mkdir(parents=True)
        session = ParcelSession("SCANCODE-TEST-001", "SCANCODE-TEST-001", local, 1280, 720, 20, "QA Station", "QA")
        cv2.imwrite(str(session.waybill_path), crop)
        for _ in range(25):
            session.write(frame)
        meta = session.finalize()
        assert session.final_path.exists() and session.final_path.stat().st_size > 1024
        assert session.metadata_path.exists()
        assert json.loads(session.metadata_path.read_text())["code"] == "SCANCODE-TEST-001"

        bundles = pending_bundles(Path(td))
        assert len(bundles) == 1
        server = Path(sd)
        copied = sync_bundle(*bundles[0], server)
        assert copied
        assert not session.final_path.exists()
        assert (server / "2026-08-18" / "SCANCODE-TEST-001.avi").exists()
        assert (server / "2026-08-18" / "SCANCODE-TEST-001.json").exists()

    print("NATIVE CORE PASS: barcode decode, quality, waybill, video record, metadata, SHA-verified server sync")


if __name__ == "__main__":
    main()

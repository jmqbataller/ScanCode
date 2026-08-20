from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

import scancode_app_v50_final as finalmod
import scancode_scanner_v50 as scanmod
from scancode_v5_services import (
    EvidenceDB,
    SubmissionQueue,
    best_frame,
    choose_tracking_candidate,
    detect_courier,
    normalize_code,
    tracking_score,
    validate_tracking,
    verify_integrity,
)


def main():
    here = Path(__file__).resolve().parent
    manifest = json.loads((here / "v5_feature_manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "5.0.0"
    assert len(manifest["features"]) == 30
    assert all(f["status"] in {"implemented", "retained"} for f in manifest["features"])

    candidates = [
        ("12345678", "EAN8"),
        ("SPXPH1234567890", "Code128"),
        ("ORDER123", "QRCode"),
    ]
    best = choose_tracking_candidate(candidates)
    assert best == ("SPXPH1234567890", "Code128"), best
    assert detect_courier(best[0]) == "SPX"
    assert tracking_score(*best) > tracking_score("12345678", "EAN8")
    assert validate_tracking(best[0])[0] is True
    assert validate_tracking("ABC")[0] is False
    assert normalize_code(" spx 123 ") == "SPX123"

    settings = {
        "smart_scan_zone": True,
        "scan_zone_ratio": 0.70,
        "waybill_focus": True,
        "waybill_focus_mode": "Auto",
    }
    scanner = scanmod.SmartScanner(lambda: settings)
    original = scanmod.read_codes_optimized
    try:
        calls = []
        def fake_reader(frame, filter_mode, zoom):
            calls.append((frame.shape[:2], filter_mode, zoom))
            return [("JT123456789PH", "Code128"), ("QR-PARCEL-001", "QRCode")]
        scanmod.read_codes_optimized = fake_reader
        frame = np.full((1080, 1920, 3), 220, dtype=np.uint8)
        found = scanner.read(frame, "QR + Barcode", 1.85)
        assert ("JT123456789PH", "Code128") in found
        assert ("QR-PARCEL-001", "QRCode") in found
        assert calls and calls[0][0][0] < 1080 and calls[0][0][1] < 1920
        assert calls[0][2] in {1.35, 2.15}
    finally:
        scanmod.read_codes_optimized = original

    soft = np.full((200, 300, 3), 180, dtype=np.uint8)
    sharp = soft.copy()
    cv2.rectangle(sharp, (40, 40), (260, 160), (0, 0, 0), 4)
    selected = best_frame([soft, sharp])
    assert selected is not None
    assert float(cv2.Laplacian(cv2.cvtColor(selected, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()) > 0

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db = EvidenceDB(root / "evidence.db")
        queue = SubmissionQueue(root / "queue.json")
        now = time.time()
        db.upsert({
            "code": "JT123456789PH",
            "courier": "J&T",
            "operator": "Operator 1",
            "station": "Station 01",
            "started_at": now - 10,
            "ended_at": now,
            "duration_ms": 10000,
            "bigseller_status": "VERIFIED",
            "quality_status": "PASS",
            "integrity_status": "VERIFIED",
        })
        db.event("JT123456789PH", "WAYBILL_SCANNED", "J&T")
        db.event("JT123456789PH", "BIGSELLER_VERIFIED", "success")
        assert db.exists("JT123456789PH")
        assert len(db.search("JT123")) == 1
        assert len(db.timeline("JT123456789PH")) == 2
        stats = db.dashboard(24)
        assert stats["total"] == 1 and stats["submitted"] == 1

        queue.enqueue("JT123456789PH", "J&T", "BigSeller offline")
        assert queue.count() == 1
        queue.update("JT123456789PH", "VERIFIED", increment_attempt=True)
        assert queue.count() == 0

        # Critical safety rule: an ambiguous submission is NOT retryable. It may
        # already have been accepted by BigSeller and must remain manual-review.
        queue.enqueue("SPXPH987654321", "SPX")
        queue.update("SPXPH987654321", "PENDING_VERIFY")
        assert queue.count() == 0, queue.pending()

        video = root / "video.bin"
        waybill = root / "waybill.bin"
        video.write_bytes(b"video-evidence")
        waybill.write_bytes(b"waybill-evidence")
        from scancode_v5_services import sha256_file
        result = verify_integrity(video, waybill, sha256_file(video), sha256_file(waybill))
        assert result["ok"] is True
        video.write_bytes(b"tampered")
        result2 = verify_integrity(video, waybill, result["video"], result["waybill"])
        assert result2["ok"] is False

    defaults = finalmod.ScanCodeApp.__new__(finalmod.ScanCodeApp).defaults()
    assert defaults["scan_target"] == "BigSeller"
    assert defaults["barcode_filter"] == "QR + Barcode"
    assert defaults["auto_pack_session"] is True
    assert defaults["smart_scan_zone"] is True
    assert defaults["best_waybill_shot"] is True
    assert defaults["duplicate_protection"] is True
    assert defaults["bigseller_verify"] is True
    assert defaults["bigseller_retry"] is True
    assert defaults["retention_days"] == 14
    assert defaults["waybill_focus_mode"] == "Auto"

    print("SCANCODE V5 PASS: 30 features, smart scanner, evidence DB, retry safety and integrity verified.")


if __name__ == "__main__":
    main()

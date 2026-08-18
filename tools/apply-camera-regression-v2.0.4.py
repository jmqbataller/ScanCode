from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text, old, new, label):
    if old not in text:
        raise RuntimeError(f"Patch anchor not found: {label}")
    return text.replace(old, new, 1)


# ---------------- main.js ----------------
main_path = ROOT / 'main.js'
main = main_path.read_text(encoding='utf-8')

# Restore the renderer loading path that was proven to work with the user's
# built-in HP TrueVision camera in ScanCode v1.3.
main = main.replace("  mainWindow.loadURL('scancode://app/index.html');", "  mainWindow.loadFile(path.join(__dirname, 'src', 'index.html'));")
main = main.replace("  registerScanCodeProtocol();\n", "")

# Restore the simpler media permission flow from the last known-working build.
permission_pattern = re.compile(
    r"  // Permit media only for the trusted ScanCode renderer\.[\s\S]*?session\.defaultSession\.setPermissionRequestHandler\(\(webContents, permission, callback\) => \{\n    callback\(permission === 'media' && trustedMediaContents\(webContents\)\);\n  \}\);\n"
)
permission_replacement = """  // Known-working camera permission flow from ScanCode v1.3.\n  // Chromium still asks Electron before opening a webcam; allow media for the\n  // local ScanCode renderer.\n  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {\n    callback(permission === 'media');\n  });\n"""
main, n = permission_pattern.subn(permission_replacement, main, count=1)
if n != 1:
    raise RuntimeError('Could not restore known-working media permission handler')

main_path.write_text(main, encoding='utf-8')


# ---------------- renderer.js ----------------
renderer_path = ROOT / 'src' / 'renderer.js'
renderer = renderer_path.read_text(encoding='utf-8')

# Replace only the camera opener. Keep all newer recording, server sync,
# evidence, quality, watchdog and BigSeller features around it.
working_start_camera = r'''async function startCamera(requestedDeviceId = '') {
  currentCameraMode = 'local';
  stopPhoneMode();

  const token = ++cameraStartToken;
  cameraStarting = true;
  cameraLastFailureAt = 0;
  stopLocalCamera();

  els.video.style.display = 'block';
  els.phoneFrame.style.display = 'none';
  els.cameraMessage.textContent = 'Starting camera…';
  els.cameraMessage.classList.remove('hidden');
  badge(els.cameraBadge, 'CAMERA STARTING', 'warning');

  codeReader = new BrowserMultiFormatReader();
  canvasCodeReader = new BrowserMultiFormatReader();

  // This is the same camera-opening method used by ScanCode v1.3, which was
  // confirmed working on the user's built-in HP TrueVision camera. ZXing owns
  // the single webcam stream and attaches it directly to the existing <video>.
  const selected = requestedDeviceId || els.cameraSelect.value || '';
  const constraints = {
    video: {
      width: { ideal: 1280 },
      height: { ideal: 720 },
      frameRate: { ideal: 30, max: 30 },
      ...(selected ? { deviceId: { exact: selected } } : {})
    },
    audio: false
  };

  try {
    scannerControls = await codeReader.decodeFromConstraints(
      constraints,
      els.video,
      (result, error) => {
        if (result) processDetectedResult(result, 'camera');
      }
    );

    if (token !== cameraStartToken) {
      try { scannerControls?.stop(); } catch {}
      return;
    }

    await els.video.play();

    const stream = els.video.srcObject;
    const track = stream?.getVideoTracks?.()[0];
    if (!track || track.readyState !== 'live') {
      throw new Error('Camera opened but no live video track was returned.');
    }

    localCameraStream = stream;
    const activeDeviceId = track.getSettings?.().deviceId || selected;
    const activeLabel = track.label || 'Built-in / Default Camera';

    els.cameraMessage.classList.add('hidden');
    badge(els.cameraBadge, 'CAMERA LIVE', 'good');

    await loadCameraList(activeDeviceId).catch(() => {});
    await applyContinuousAutofocus().catch(() => {});
    startLocalZoomScanner();

    lastVideoTime = els.video.currentTime || 0;
    lastVideoAdvancedAt = Date.now();
    cameraLastFailureAt = 0;
    showToast(`Camera ready: ${activeLabel}`);
  } catch (err) {
    console.error('Camera start failed:', err);
    stopLocalCamera();
    cameraLastFailureAt = Date.now();

    const sys = await ipcRenderer.invoke('camera:system-status').catch(() => null);
    const name = err?.name || '';
    let message = err?.message || 'Camera could not start.';

    if (sys?.cameraAccess === 'denied' || sys?.cameraAccess === 'restricted') {
      message = 'Windows camera access is blocked. Enable Camera access and “Let desktop apps access your camera” in Windows Settings.';
    } else if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
      message = 'Camera permission denied. Enable Camera access for desktop apps in Windows Privacy settings.';
    } else if (name === 'NotReadableError' || name === 'TrackStartError') {
      message = 'Camera is busy/locked. Close Windows Camera, Zoom, Teams, Discord or OBS, then click Restart camera.';
    } else if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
      message = 'No camera was reported by Windows/Chromium.';
    }

    els.cameraMessage.textContent = `CAMERA ERROR — ${message}`;
    els.cameraMessage.classList.remove('hidden');
    badge(els.cameraBadge, 'CAMERA ERROR', 'bad');
    showToast(message);
  } finally {
    if (token === cameraStartToken) cameraStarting = false;
  }
}

'''
renderer, n = re.subn(
    r"async function startCamera\(requestedDeviceId = ''\) \{[\s\S]*?\n\}\n\n(?=async function saveSettingsFromUi)",
    lambda m: working_start_camera,
    renderer,
    count=1
)
if n != 1:
    raise RuntimeError('Could not replace startCamera with the known-working v1.3 pipeline')

# Diagnostics should describe the real direct ZXing pipeline, not the discarded
# secure-origin experiment.
renderer = renderer.replace(
    "  const message = `Windows access: ${sys?.cameraAccess || 'unknown'} | ${deviceText} | Secure: ${window.isSecureContext ? 'YES' : 'NO'} | Origin: ${location.origin} | Electron ${sys?.electron || '?'}`;",
    "  const message = `Windows access: ${sys?.cameraAccess || 'unknown'} | ${deviceText} | Pipeline: ZXing direct webcam | Electron ${sys?.electron || '?'}`;"
)

renderer_path.write_text(renderer, encoding='utf-8')


# ---------------- index.html ----------------
html_path = ROOT / 'src' / 'index.html'
html = html_path.read_text(encoding='utf-8')
html = re.sub(r'<span class="version-tag">v[^<]+</span>', '<span class="version-tag">v2.0.4</span>', html, count=1)
html_path.write_text(html, encoding='utf-8')


# ---------------- package.json ----------------
pkg_path = ROOT / 'package.json'
pkg = json.loads(pkg_path.read_text(encoding='utf-8'))
pkg['version'] = '2.0.4'
pkg['description'] = 'ScanCode v2.0.4 camera regression fix restoring the proven ZXing direct webcam pipeline from v1.3 while retaining warehouse evidence, BigSeller bridge, server sync, QA and diagnostics.'
pkg.setdefault('scripts', {})['dist'] = 'electron-builder --win nsis portable --publish never'
pkg['scripts']['dist:setup'] = 'electron-builder --win nsis --publish never'
pkg_path.write_text(json.dumps(pkg, indent=2) + '\n', encoding='utf-8')


# ---------------- QA ----------------
qa_path = ROOT / 'qa' / 'qa.js'
qa = qa_path.read_text(encoding='utf-8')
qa = qa.replace(
    "check('Camera device selector has a visible fallback', html.includes('Default / Built-in Camera') && renderer.includes('getUserMediaWithTimeout'));",
    "check('Camera device selector has a visible fallback', html.includes('Default / Built-in Camera') && renderer.includes('decodeFromConstraints'));"
)
qa = qa.replace(
    "check('Camera startup avoids temporary probe stream', !initBlock.includes('const probe = await navigator.mediaDevices.getUserMedia') && renderer.includes('localCameraStream') && renderer.includes('getUserMediaWithTimeout'));",
    "check('Camera startup uses known-working direct ZXing pipeline', !initBlock.includes('const probe = await navigator.mediaDevices.getUserMedia') && renderer.includes('decodeFromConstraints') && renderer.includes('localCameraStream'));"
)
qa = qa.replace(
    "check('Secure ScanCode renderer origin', main.includes('registerSchemesAsPrivileged') && main.includes(\"scancode://app/index.html\") && main.includes(\"secure: true\"));",
    "check('Known-working local renderer camera path', main.includes('mainWindow.loadFile') && renderer.includes('decodeFromConstraints'));"
)
qa = qa.replace(
    "check('Camera request timeout is self-cleaning', renderer.includes('clearTimeout(timer)') && renderer.includes('getUserMediaWithTimeout'));",
    "check('Camera stream is opened once by ZXing', renderer.includes('decodeFromConstraints') && !renderer.includes('stream = await getUserMediaWithTimeout(attempt.constraints'));"
)
qa = qa.replace(
    "check('Complete Electron media permission handling', main.includes('setPermissionCheckHandler') && main.includes('setPermissionRequestHandler'));",
    "check('Electron media permission handler present', main.includes('setPermissionRequestHandler'));"
)
qa_path.write_text(qa, encoding='utf-8')

print('ScanCode v2.0.4 known-working camera regression patch applied.')

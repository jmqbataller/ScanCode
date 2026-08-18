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
main = replace_once(
    main,
    "const { app, BrowserWindow, ipcMain, dialog, shell, session, systemPreferences } = require('electron');",
    "const { app, BrowserWindow, ipcMain, dialog, shell, session, systemPreferences, protocol, net } = require('electron');",
    'electron imports'
)

scheme_block = """

// Serve the renderer from a secure, standard app origin instead of file://.
// This keeps relative resources working while giving Chromium a proper secure
// origin for media APIs such as navigator.mediaDevices.getUserMedia().
protocol.registerSchemesAsPrivileged([
  {
    scheme: 'scancode',
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      stream: true,
      codeCache: true
    }
  }
]);
"""
if 'protocol.registerSchemesAsPrivileged' not in main:
    main = replace_once(main, "const { pathToFileURL } = require('url');\n", "const { pathToFileURL } = require('url');\n" + scheme_block, 'scheme registration')

protocol_function = r'''
function registerScanCodeProtocol() {
  const sourceRoot = path.resolve(__dirname, 'src');
  protocol.handle('scancode', (request) => {
    try {
      const requestUrl = new URL(request.url);
      let relativePath = decodeURIComponent(requestUrl.pathname || '/');
      if (relativePath === '/' || relativePath === '') relativePath = '/index.html';
      relativePath = relativePath.replace(/^[/\\]+/, '');

      const filePath = path.resolve(sourceRoot, relativePath);
      const allowedRoot = `${sourceRoot}${path.sep}`;
      if (filePath !== path.join(sourceRoot, 'index.html') && !filePath.startsWith(allowedRoot)) {
        return new Response('Not found', { status: 404 });
      }
      if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
        return new Response('Not found', { status: 404 });
      }
      return net.fetch(pathToFileURL(filePath).toString());
    } catch (err) {
      return new Response(`ScanCode resource error: ${err.message}`, { status: 500 });
    }
  });
}

'''
if 'function registerScanCodeProtocol()' not in main:
    main = replace_once(main, 'function createWindow() {', protocol_function + 'function createWindow() {', 'protocol handler function')

main = replace_once(
    main,
    "  mainWindow.loadFile(path.join(__dirname, 'src', 'index.html'));",
    "  mainWindow.loadURL('scancode://app/index.html');",
    'secure renderer URL'
)

main = replace_once(
    main,
    "app.whenReady().then(() => {\n",
    "app.whenReady().then(() => {\n  registerScanCodeProtocol();\n",
    'protocol registration on ready'
)

old_permissions = """  // Electron requires BOTH permission-check and permission-request handlers
  // for complete media permission handling. This is especially important for
  // getUserMedia() on file:// renderer pages.
  session.defaultSession.setPermissionCheckHandler((webContents, permission, requestingOrigin, details) => {
    if (permission === 'media') return true;
    return false;
  });
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback, details) => {
    callback(permission === 'media');
  });
"""
new_permissions = """  // Permit media only for the trusted ScanCode renderer. The renderer now runs
  // from the secure scancode://app origin instead of file://.
  const trustedMediaContents = (webContents) => {
    try {
      return Boolean(webContents && (
        webContents === mainWindow?.webContents ||
        String(webContents.getURL?.() || '').startsWith('scancode://app')
      ));
    } catch {
      return false;
    }
  };
  session.defaultSession.setPermissionCheckHandler((webContents, permission, requestingOrigin) => {
    if (permission !== 'media') return false;
    return String(requestingOrigin || '').startsWith('scancode://app') || trustedMediaContents(webContents);
  });
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    callback(permission === 'media' && trustedMediaContents(webContents));
  });
"""
main = replace_once(main, old_permissions, new_permissions, 'media permission handlers')
main_path.write_text(main, encoding='utf-8')


# ---------------- renderer.js ----------------
renderer_path = ROOT / 'src' / 'renderer.js'
renderer = renderer_path.read_text(encoding='utf-8')

renderer = replace_once(
    renderer,
    "let lastPhoneFrameAt = 0;",
    "let lastPhoneFrameAt = 0;\nlet cameraStarting = false;\nlet cameraLastFailureAt = 0;",
    'camera state flags'
)

new_gum = r'''async function getUserMediaWithTimeout(constraints, ms = 7000) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      const err = new Error(`Camera did not respond within ${Math.round(ms / 1000)} seconds.`);
      err.name = 'TimeoutError';
      reject(err);
    }, ms);

    navigator.mediaDevices.getUserMedia(constraints).then((stream) => {
      if (settled) {
        try { stream.getTracks().forEach(track => track.stop()); } catch {}
        return;
      }
      settled = true;
      clearTimeout(timer);
      resolve(stream);
    }).catch((err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(err);
    });
  });
}

'''
renderer, count = re.subn(
    r"async function getUserMediaWithTimeout\(constraints, ms = 8000\) \{[\s\S]*?\n\}\n\n(?=async function waitForVideoReady)",
    lambda m: new_gum,
    renderer,
    count=1
)
if count != 1:
    raise RuntimeError('Could not replace getUserMediaWithTimeout')

new_start_camera = r'''async function startCamera(requestedDeviceId = '') {
  currentCameraMode = 'local';
  stopPhoneMode();

  const token = ++cameraStartToken;
  cameraStarting = true;
  cameraLastFailureAt = 0;
  stopLocalCamera();

  els.video.style.display = 'block';
  els.phoneFrame.style.display = 'none';
  els.cameraMessage.textContent = requestedDeviceId ? 'Opening selected camera…' : 'Opening default / built-in camera…';
  els.cameraMessage.classList.remove('hidden');
  badge(els.cameraBadge, 'CAMERA STARTING', 'warning');

  codeReader = new BrowserMultiFormatReader();
  canvasCodeReader = new BrowserMultiFormatReader();

  // Do not stack multiple fallback requests for the same physical camera.
  // A selected device may fall back once to the Windows default camera.
  const attempts = requestedDeviceId
    ? [
        { name: 'selected camera', constraints: { video: { deviceId: { exact: requestedDeviceId } }, audio: false } },
        { name: 'default camera', constraints: { video: true, audio: false } }
      ]
    : [
        { name: 'default camera', constraints: { video: true, audio: false } }
      ];

  let stream = null;
  let lastError = null;

  try {
    for (const attempt of attempts) {
      if (token !== cameraStartToken) return;
      try {
        els.cameraMessage.textContent = `Trying ${attempt.name}…`;
        stream = await getUserMediaWithTimeout(attempt.constraints, 7000);
        if (stream) break;
      } catch (err) {
        console.warn(`Camera attempt failed: ${attempt.name}`, err);
        lastError = err;

        // Permission denial, camera-busy, or timeout will not be fixed by
        // immediately issuing another request. Avoid camera request loops.
        if (['NotAllowedError', 'PermissionDeniedError', 'NotReadableError', 'TrackStartError', 'TimeoutError'].includes(err?.name)) {
          break;
        }
        await sleep(250);
      }
    }

    if (!stream) throw lastError || new Error('No camera stream was returned.');

    if (token !== cameraStartToken) {
      stream.getTracks().forEach(track => track.stop());
      return;
    }

    localCameraStream = stream;
    els.video.srcObject = stream;
    els.video.muted = true;
    els.video.autoplay = true;
    els.video.playsInline = true;

    const playPromise = els.video.play();
    await waitForVideoReady(els.video, 5000);
    await promiseWithTimeout(playPromise, 5000, 'Camera playback');

    const track = stream.getVideoTracks()[0];
    if (!track || track.readyState !== 'live') throw new Error('Camera track did not become live.');

    const activeDeviceId = track.getSettings?.().deviceId || '';
    const activeLabel = track.label || 'Built-in / Default Camera';

    await promiseWithTimeout(loadCameraList(activeDeviceId), 3500, 'Camera list').catch((err) => {
      console.warn('Camera list refresh skipped:', err);
      els.cameraSelect.innerHTML = '';
      const opt = document.createElement('option');
      opt.value = activeDeviceId;
      opt.textContent = activeLabel;
      els.cameraSelect.appendChild(opt);
    });

    await applyContinuousAutofocus().catch(() => {});
    startLocalZoomScanner();

    cameraLastFailureAt = 0;
    els.cameraMessage.classList.add('hidden');
    badge(els.cameraBadge, 'CAMERA LIVE', 'good');
    lastVideoTime = els.video.currentTime || 0;
    lastVideoAdvancedAt = Date.now();
    showToast(`Camera ready: ${activeLabel}`);
  } catch (err) {
    console.error('Camera start failed:', err);
    stopLocalCamera();
    cameraLastFailureAt = Date.now();

    const sys = await ipcRenderer.invoke('camera:system-status').catch(() => null);
    const name = err?.name || '';
    let message = err?.message || 'Camera could not start.';

    if (!window.isSecureContext) {
      message = `Camera blocked because the app origin is not secure (${location.origin}). Reinstall the latest ScanCode build.`;
    } else if (sys?.cameraAccess === 'denied' || sys?.cameraAccess === 'restricted') {
      message = 'Windows camera access is blocked. Enable Camera access and “Let desktop apps access your camera” in Windows Settings.';
    } else if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
      message = 'Camera permission denied. Enable Camera access for desktop apps in Windows Privacy settings.';
    } else if (name === 'NotReadableError' || name === 'TrackStartError') {
      message = 'Camera is busy/locked. Close Windows Camera, Zoom, Teams, Discord or OBS, then click Restart camera.';
    } else if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
      message = 'Windows/Chromium did not report a camera device.';
    } else if (name === 'TimeoutError') {
      message = 'Camera startup timed out. The driver did not answer the request. Close other camera apps, then click Restart camera.';
    }

    els.cameraMessage.textContent = message;
    els.cameraMessage.classList.remove('hidden');
    badge(els.cameraBadge, 'CAMERA ERROR', 'bad');
    showToast(message);
  } finally {
    if (token === cameraStartToken) cameraStarting = false;
  }
}

'''
renderer, count = re.subn(
    r"async function startCamera\(requestedDeviceId = ''\) \{[\s\S]*?\n\}\n\n(?=async function saveSettingsFromUi)",
    lambda m: new_start_camera,
    renderer,
    count=1
)
if count != 1:
    raise RuntimeError('Could not replace startCamera')

renderer = replace_once(
    renderer,
    "  const message = `Windows access: ${sys?.cameraAccess || 'unknown'} | ${deviceText} | Electron ${sys?.electron || '?'}`;",
    "  const message = `Windows access: ${sys?.cameraAccess || 'unknown'} | ${deviceText} | Secure: ${window.isSecureContext ? 'YES' : 'NO'} | Origin: ${location.origin} | Electron ${sys?.electron || '?'}`;",
    'diagnostics message'
)

renderer = replace_once(
    renderer,
    "els.restartCameraBtn.addEventListener('click', async () => {\n  showToast('Restarting camera…');",
    "els.restartCameraBtn.addEventListener('click', async () => {\n  cameraLastFailureAt = 0;\n  showToast('Restarting camera…');",
    'manual restart reset'
)

renderer = replace_once(
    renderer,
    "navigator.mediaDevices?.addEventListener?.('devicechange', async () => {\n  if (currentCameraMode !== 'local') return;",
    "navigator.mediaDevices?.addEventListener?.('devicechange', async () => {\n  if (currentCameraMode !== 'local' || cameraStarting) return;",
    'device change guard'
)

renderer = replace_once(
    renderer,
    "ipcRenderer.on('watchdog:tick', async () => {\n  if (watchdogRestarting) return;",
    "ipcRenderer.on('watchdog:tick', async () => {\n  if (watchdogRestarting || cameraStarting) return;\n  if (cameraLastFailureAt && Date.now() - cameraLastFailureAt < 30000) return;",
    'watchdog startup guard'
)

renderer = replace_once(
    renderer,
    "    els.cameraSelect.innerHTML = '<option value=\"\">Default / Built-in Camera</option>';\n    await startCamera('');",
    "    els.cameraSelect.innerHTML = '<option value=\"\">Default / Built-in Camera</option>';\n    // Let the secure renderer finish its first paint before requesting the webcam.\n    await sleep(300);\n    await startCamera('');",
    'camera startup delay'
)

renderer_path.write_text(renderer, encoding='utf-8')


# ---------------- index.html ----------------
html_path = ROOT / 'src' / 'index.html'
html = html_path.read_text(encoding='utf-8')
html = html.replace('<span class="version-tag">v2.0</span>', '<span class="version-tag">v2.0.3</span>', 1)
html_path.write_text(html, encoding='utf-8')


# ---------------- package.json ----------------
pkg_path = ROOT / 'package.json'
pkg = json.loads(pkg_path.read_text(encoding='utf-8'))
pkg['version'] = '2.0.3'
pkg['description'] = 'ScanCode v2.0.3 camera stabilization build using a secure Electron app origin, guarded camera watchdog startup, robust webcam timeouts, warehouse evidence recording, BigSeller bridge, and server sync.'
pkg.setdefault('scripts', {})['dist'] = 'electron-builder --win nsis portable --publish never'
pkg['scripts']['dist:setup'] = 'electron-builder --win nsis --publish never'
pkg_path.write_text(json.dumps(pkg, indent=2) + '\n', encoding='utf-8')


# ---------------- QA ----------------
qa_path = ROOT / 'qa' / 'qa.js'
qa = qa_path.read_text(encoding='utf-8')
qa_anchor = "// Environment-dependent features\n"
extra_checks = """check('Secure ScanCode renderer origin', main.includes('registerSchemesAsPrivileged') && main.includes("scancode://app/index.html") && main.includes("secure: true"));
check('Camera watchdog cannot interrupt startup', renderer.includes('watchdogRestarting || cameraStarting') && renderer.includes('cameraLastFailureAt'));
check('Camera request timeout is self-cleaning', renderer.includes('clearTimeout(timer)') && renderer.includes('getUserMediaWithTimeout'));

"""
if "check('Secure ScanCode renderer origin'" not in qa:
    qa = replace_once(qa, qa_anchor, extra_checks + qa_anchor, 'QA camera checks')
qa_path.write_text(qa, encoding='utf-8')


# ---------------- README ----------------
readme_path = ROOT / 'README.md'
readme = readme_path.read_text(encoding='utf-8')
if '## v2.0.3 — Camera Stabilization' not in readme:
    readme += """

## v2.0.3 — Camera Stabilization

- Renderer is now served from a secure `scancode://app` origin instead of `file://`.
- Camera permission handlers are restricted to the trusted ScanCode renderer.
- Fixed a watchdog race that could restart/cancel the webcam while it was still opening.
- Camera startup no longer stacks redundant default-camera requests after a timeout/busy error.
- Camera request timeout cleanup was hardened.
- Failed camera startup pauses automatic watchdog retries for 30 seconds; manual Restart remains available immediately.
- Diagnose now shows Windows camera access, camera enumeration, secure-context state, renderer origin, and Electron version.
"""
readme_path.write_text(readme, encoding='utf-8')

print('ScanCode v2.0.3 camera stabilization patch applied successfully.')

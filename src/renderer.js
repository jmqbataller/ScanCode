const { ipcRenderer, clipboard } = require('electron');
const { BrowserMultiFormatReader } = require('@zxing/browser');

const $ = (id) => document.getElementById(id);

const els = {
  video: $('video'),
  videoStage: $('videoStage'),
  recordingOverlay: $('recordingOverlay'),
  phoneFrame: $('phoneFrame'),
  scanCanvas: $('scanCanvas'),
  canvas: $('recordCanvas'),
  cameraMode: $('cameraMode'),
  cameraMessage: $('cameraMessage'),
  cameraSelect: $('cameraSelect'),
  phoneBridgePanel: $('phoneBridgePanel'),
  phoneUrls: $('phoneUrls'),
  networkCameraUrl: $('networkCameraUrl'),
  farViewZoom: $('farViewZoom'),
  farViewZoomValue: $('farViewZoomValue'),
  scannerZoom: $('scannerZoom'),
  scannerZoomValue: $('scannerZoomValue'),
  cameraFocusStatus: $('cameraFocusStatus'),
  connectNetworkCameraBtn: $('connectNetworkCameraBtn'),
  restartCameraBtn: $('restartCameraBtn'),
  diagnoseCameraBtn: $('diagnoseCameraBtn'),
  cameraBadge: $('cameraBadge'),
  qualityBadge: $('qualityBadge'),
  syncBadge: $('syncBadge'),
  recordBadge: $('recordBadge'),
  currentCode: $('currentCode'),
  timer: $('timer'),
  recDot: $('recDot'),
  manualCode: $('manualCode'),
  manualScanBtn: $('manualScanBtn'),
  lookupState: $('lookupState'),
  detailTracking: $('detailTracking'),
  detailOrder: $('detailOrder'),
  detailCourier: $('detailCourier'),
  detailCustomer: $('detailCustomer'),
  detailItem: $('detailItem'),
  detailQty: $('detailQty'),
  detailStatus: $('detailStatus'),
  stationName: $('stationName'),
  operatorName: $('operatorName'),
  overlapMs: $('overlapMs'),
  successSoundEnabled: $('successSoundEnabled'),
  testSoundBtn: $('testSoundBtn'),
  todayFolder: $('todayFolder'),
  openFolderBtn: $('openFolderBtn'),
  folderPath: $('folderPath'),
  serverFolder: $('serverFolder'),
  autoSyncEnabled: $('autoSyncEnabled'),
  chooseServerFolderBtn: $('chooseServerFolderBtn'),
  syncNowBtn: $('syncNowBtn'),
  openServerBtn: $('openServerBtn'),
  syncStatusText: $('syncStatusText'),
  exceptionType: $('exceptionType'),
  markExceptionBtn: $('markExceptionBtn'),
  exceptionStatus: $('exceptionStatus'),
  bigSellerAutoSubmit: $('bigSellerAutoSubmit'),
  bigSellerUrl: $('bigSellerUrl'),
  openBigSellerBtn: $('openBigSellerBtn'),
  bigSellerStatus: $('bigSellerStatus'),
  autoStartWithWindows: $('autoStartWithWindows'),
  cameraQualityEnabled: $('cameraQualityEnabled'),
  scanConfirmations: $('scanConfirmations'),
  barcodeFilter: $('barcodeFilter'),
  endShiftBtn: $('endShiftBtn'),
  shiftStatus: $('shiftStatus'),
  serverSearchInput: $('serverSearchInput'),
  serverSearchBtn: $('serverSearchBtn'),
  serverSearchResults: $('serverSearchResults'),
  serverVideoPlayer: $('serverVideoPlayer'),
  serverWaybillPreview: $('serverWaybillPreview'),
  startVideoBtn: $('startVideoBtn'),
  pauseVideoBtn: $('pauseVideoBtn'),
  stopVideoBtn: $('stopVideoBtn'),
  transportStatus: $('transportStatus'),
  historyBody: $('historyBody'),
  scanCount: $('scanCount'),
  toast: $('toast')
};

let codeReader = null;
let scannerControls = null;
let localCameraStream = null;
let cameraStartToken = 0;
let currentSession = null;
let activeDetails = null;
let settings = null;
let farViewZoom = 1.0;
let scannerZoom = 1.75;
let localScanTimer = null;
let localFrameScanning = false;
let canvasCodeReader = null;
let animationId = null;
let timerId = null;
let savedCount = 0;
let scanBusy = false;
const historyFiles = new Map();
let lastAccepted = { code: null, at: 0 };
const pendingStops = new Set();
let phonePollTimer = null;
let phoneScanTimer = null;
let phoneBlobUrl = null;
let phoneScanning = false;
let phoneInfo = { urls: [] };
let currentCameraMode = 'local';
let scanCandidate = { code: null, format: null, count: 0, lastAt: 0 };
let qualityTimer = null;
let lastVideoTime = -1;
let lastVideoAdvancedAt = Date.now();
let watchdogRestarting = false;
let lastPhoneFrameAt = 0;
let cameraStarting = false;
let cameraLastFailureAt = 0;

const SCAN_DEBOUNCE_MS = 1400;

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.add('show');
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => els.toast.classList.remove('show'), 2200);
}

function badge(el, text, state = 'neutral') {
  el.textContent = text;
  el.className = `${el.classList.contains('mini-state') ? 'mini-state' : 'badge'} ${state}`;
}

function cleanCode(raw) {
  return String(raw || '').trim().replace(/[\r\n]+/g, '');
}

function formatDuration(ms) {
  const total = Math.max(0, Math.round(ms / 1000));
  const m = String(Math.floor(total / 60)).padStart(2, '0');
  const s = String(total % 60).padStart(2, '0');
  return `${m}:${s}`;
}

function localTime(isoOrMs) {
  const d = new Date(isoOrMs);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function deterministicParcel(code) {
  let hash = 0;
  for (let i = 0; i < code.length; i++) hash = ((hash << 5) - hash + code.charCodeAt(i)) | 0;
  const n = Math.abs(hash);
  const couriers = ['Shopee Express', 'J&T Express', 'Flash Express', 'LBC', 'Ninja Van'];
  const items = [
    'Demo Item — Apparel',
    'Demo Item — Accessories',
    'Demo Item — Home Goods',
    'Demo Item — Electronics',
    'Demo Item — General Merchandise'
  ];

  return {
    tracking: code,
    order: `DEMO-${String(n % 1000000).padStart(6, '0')}`,
    courier: couriers[n % couriers.length],
    customer: `Demo Customer ${String.fromCharCode(65 + (n % 26))}.`,
    item: items[n % items.length],
    qty: (n % 4) + 1,
    status: 'Ready for packing'
  };
}

async function lookupParcel(code) {
  // V1 DEMO INTEGRATION.
  // Tomorrow, replace this body with the real API/site adapter.
  // Keep the returned object fields the same so the scanner/recorder needs no rewrite.
  await new Promise(r => setTimeout(r, 180));
  return deterministicParcel(code);
}

function setDetails(details) {
  activeDetails = details;
  els.detailTracking.textContent = details?.tracking || '—';
  els.detailOrder.textContent = details?.order || '—';
  els.detailCourier.textContent = details?.courier || '—';
  els.detailCustomer.textContent = details?.customer || '—';
  els.detailItem.textContent = details?.item || '—';
  els.detailQty.textContent = details?.qty ?? '—';
  els.detailStatus.textContent = details?.status || '—';
}

function setLookupPending(code) {
  activeDetails = {
    tracking: code,
    order: 'Looking up…',
    courier: '—',
    customer: '—',
    item: '—',
    qty: '—',
    status: 'Scanning'
  };
  setDetails(activeDetails);
  badge(els.lookupState, 'LOOKUP', 'warning');
}

function getCanvasStream() {
  if (!els.canvas.captureStream) {
    throw new Error('Canvas recording is not supported on this system.');
  }
  return els.canvas.captureStream(30);
}

function preferredMime() {
  const types = [
    'video/webm;codecs=vp9',
    'video/webm;codecs=vp8',
    'video/webm'
  ];
  return types.find(t => MediaRecorder.isTypeSupported(t)) || '';
}

function startSession(code) {
  const stream = getCanvasStream();
  const chunks = [];
  const mimeType = preferredMime();
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType, videoBitsPerSecond: 4500000 } : undefined);

  const session = {
    code,
    recorder,
    chunks,
    startedAt: Date.now(),
    endedAt: null,
    stopping: false,
    exception: null,
    recoveryPath: null,
    recoveryQueue: []
  };

  ipcRenderer.invoke('recovery:start', {
    code,
    sessionId: `${Date.now()}-${Math.random().toString(16).slice(2)}`
  }).then((r) => {
    if (!r?.ok) return;
    session.recoveryPath = r.filePath;
    const queued = session.recoveryQueue.splice(0);
    for (const buffer of queued) {
      ipcRenderer.invoke('recovery:append', { filePath: session.recoveryPath, buffer }).catch(() => {});
    }
  }).catch(() => {});

  recorder.ondataavailable = (event) => {
    if (!event.data || event.data.size <= 0) return;
    chunks.push(event.data);
    event.data.arrayBuffer().then((buffer) => {
      if (session.recoveryPath) {
        ipcRenderer.invoke('recovery:append', { filePath: session.recoveryPath, buffer }).catch(() => {});
      } else {
        session.recoveryQueue.push(buffer);
      }
    }).catch(() => {});
  };

  recorder.onerror = (event) => {
    console.error('Recorder error', event);
    showToast(`Recording error for ${code}`);
  };

  recorder.start(500);
  return session;
}

async function stopAndSaveSession(session, reason = 'next-scan') {
  if (!session || session.stopping) return;
  session.stopping = true;
  pendingStops.add(session);

  return new Promise((resolve) => {
    const finish = async () => {
      try {
        session.endedAt = Date.now();
        const blob = new Blob(session.chunks, { type: session.recorder.mimeType || 'video/webm' });
        const arrayBuffer = await blob.arrayBuffer();

        const result = await ipcRenderer.invoke('recording:save', {
          code: session.code,
          startedAt: session.startedAt,
          endedAt: session.endedAt,
          buffer: arrayBuffer,
          exception: session.exception || null,
          details: session.details || null
        });

        if (result?.ok) {
          if (session.recoveryPath) {
            await ipcRenderer.invoke('recovery:finish', { filePath: session.recoveryPath }).catch(() => {});
          }
          addHistory(result, session);
        }
      } catch (err) {
        console.error(err);
        showToast(`Could not save ${session.code}`);
      } finally {
        pendingStops.delete(session);
        resolve();
      }
    };

    session.recorder.addEventListener('stop', finish, { once: true });

    if (session.recorder.state === 'inactive') {
      finish();
    } else {
      try { session.recorder.requestData(); } catch {}
      session.recorder.stop();
    }
  });
}


const BARCODE_FORMAT_NAMES = {
  0:'AZTEC', 1:'CODABAR', 2:'CODE_39', 3:'CODE_93', 4:'CODE_128',
  5:'DATA_MATRIX', 6:'EAN_8', 7:'EAN_13', 8:'ITF', 9:'MAXICODE',
  10:'PDF_417', 11:'QR_CODE', 12:'RSS_14', 13:'RSS_EXPANDED',
  14:'UPC_A', 15:'UPC_E', 16:'UPC_EAN_EXTENSION'
};

function formatName(result) {
  try {
    const raw = result.getBarcodeFormat?.();
    if (typeof raw === 'number') return BARCODE_FORMAT_NAMES[raw] || `FORMAT_${raw}`;
    return String(raw || 'UNKNOWN');
  } catch {
    return 'UNKNOWN';
  }
}

function formatAllowed(name) {
  const mode = settings?.barcodeFilter || 'shipping';
  if (mode === 'all') return true;
  if (mode === 'qr') return name === 'QR_CODE';
  return ['QR_CODE','CODE_128','CODE_39','EAN_13','EAN_8','ITF','DATA_MATRIX','PDF_417','UPC_A','UPC_E'].includes(name);
}

function processDetectedResult(result, source = 'camera') {
  if (!result) return;
  const code = cleanCode(result.getText?.() || '');
  if (!code) return;

  const format = formatName(result);
  if (!formatAllowed(format)) return;

  const now = Date.now();
  const needed = Math.max(1, Number(settings?.scanConfirmations || 2));

  if (scanCandidate.code === code && scanCandidate.format === format && now - scanCandidate.lastAt < 1000) {
    scanCandidate.count += 1;
  } else {
    scanCandidate = { code, format, count: 1, lastAt: now };
  }
  scanCandidate.lastAt = now;

  if (scanCandidate.count >= needed) {
    scanCandidate = { code: null, format: null, count: 0, lastAt: 0 };
    handleScan(code, source);
  }
}

async function handleScan(rawCode, source = 'camera') {
  const code = cleanCode(rawCode);
  if (!code || code.length < 3) return;

  const now = Date.now();

  if (currentSession && currentSession.code === code) return;
  if (lastAccepted.code === code && now - lastAccepted.at < SCAN_DEBOUNCE_MS) return;
  if (scanBusy) return;

  scanBusy = true;
  lastAccepted = { code, at: now };

  const previous = currentSession;

  // Switch the visible overlay immediately so the next barcode is captured
  // at the beginning of the next parcel video.
  els.currentCode.textContent = code;
  setLookupPending(code);

  let next;
  try {
    next = startSession(code);
  } catch (err) {
    console.error(err);
    showToast(err.message || 'Could not start recording');
    badge(els.recordBadge, 'RECORD ERROR', 'bad');
    scanBusy = false;
    return;
  }

  currentSession = next;
  updateRecordingUi();

  if (settings?.bigSellerAutoSubmit !== false) {
    ipcRenderer.invoke('bigseller:submit', code).then((r) => {
      if (r?.ok) {
        els.bigSellerStatus.textContent = `Submitted ${code} to BigSeller input.`;
      } else if (!r?.skipped) {
        els.bigSellerStatus.textContent = r?.error || 'BigSeller bridge not ready.';
      }
    }).catch(() => {});
  }

  // Audible scan acknowledgement.
  if (settings?.successSoundEnabled !== false) beepSuccess();

  // Save a still screenshot of the waybill / QR area for this accepted parcel.
  const waybillShot = await saveWaybillSnapshot(code);
  if (waybillShot?.ok) {
    showToast(`Waybill captured: ${waybillShot.filename}`);
  }

  // Intentional overlap: new video starts immediately while the previous
  // parcel continues for a short moment. This helps capture the next QR/barcode
  // in the opening frames of its own video.
  if (previous) {
    const overlap = Number(settings?.overlapMs || 900);
    setTimeout(() => stopAndSaveSession(previous, 'next-scan'), overlap);
  }

  try {
    const details = await lookupParcel(code);
    if (currentSession?.code === code) {
      currentSession.details = details;
      setDetails(details);
      badge(els.lookupState, 'FOUND', 'good');
    }
  } catch (err) {
    console.error(err);
    if (currentSession?.code === code) {
      badge(els.lookupState, 'NOT FOUND', 'bad');
    }
  } finally {
    scanBusy = false;
  }
}


function setTransportStatus(text) {
  if (els.transportStatus) els.transportStatus.textContent = text;
}

async function pauseCurrentRecording() {
  if (!currentSession || !currentSession.recorder) {
    showToast('No active recording.');
    return;
  }
  if (currentSession.recorder.state === 'recording') {
    try {
      currentSession.recorder.pause();
      setTransportStatus(`Paused • ${currentSession.code}`);
      updateRecordingUi();
      showToast('Recording paused.');
    } catch {
      showToast('Could not pause recording.');
    }
  } else if (currentSession.recorder.state === 'paused') {
    try {
      currentSession.recorder.resume();
      setTransportStatus(`Recording • ${currentSession.code}`);
      updateRecordingUi();
      showToast('Recording resumed.');
    } catch {
      showToast('Could not resume recording.');
    }
  }
}

async function startOrResumeRecording() {
  if (currentSession?.recorder?.state === 'paused') {
    await pauseCurrentRecording();
    return;
  }
  if (currentSession?.recorder?.state === 'recording') {
    showToast('Recording already active.');
    return;
  }
  const manualCode = cleanCode(els.manualCode?.value || '') || `MANUAL-${new Date().toISOString().replace(/[:.]/g, '-')}`;
  await handleScan(manualCode, 'manual');
  setTransportStatus(`Recording • ${manualCode}`);
}

function updateRecordingUi() {
  if (currentSession && currentSession.recorder.state === 'paused') {
    badge(els.recordBadge, 'PAUSED', 'warning');
    els.recDot.classList.remove('live');
    els.videoStage?.classList.remove('recording-active');
    setTransportStatus(`Paused • ${currentSession.code}`);
  } else if (currentSession && currentSession.recorder.state !== 'inactive') {
    badge(els.recordBadge, '● RECORDING', 'bad');
    els.recDot.classList.add('live');
    els.videoStage?.classList.add('recording-active');
    setTransportStatus(`Recording • ${currentSession.code}`);
  } else {
    badge(els.recordBadge, 'NOT RECORDING', 'neutral');
    els.recDot.classList.remove('live');
    els.videoStage?.classList.remove('recording-active');
    setTransportStatus('Waiting for scan');
  }
}



function autoCropWaybill(source, sourceW, sourceH) {
  const probe = document.createElement('canvas');
  const maxW = 640;
  const scale = Math.min(1, maxW / sourceW);
  probe.width = Math.max(1, Math.round(sourceW * scale));
  probe.height = Math.max(1, Math.round(sourceH * scale));
  const pctx = probe.getContext('2d');
  drawZoomedSource(pctx, source, sourceW, sourceH, probe.width, probe.height, scannerZoom);

  const image = pctx.getImageData(0, 0, probe.width, probe.height);
  const data = image.data;
  let minX = probe.width, minY = probe.height, maxX = 0, maxY = 0, hits = 0;

  // Shipping waybills are usually relatively bright/white. Detect a broad
  // bright rectangle; if confidence is low, fall back to the scanner crop.
  for (let y = 0; y < probe.height; y += 3) {
    for (let x = 0; x < probe.width; x += 3) {
      const i = (y * probe.width + x) * 4;
      const lum = (data[i] * 0.299) + (data[i+1] * 0.587) + (data[i+2] * 0.114);
      if (lum > 175) {
        hits++;
        minX = Math.min(minX, x); minY = Math.min(minY, y);
        maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
      }
    }
  }

  const totalSamples = Math.ceil(probe.width / 3) * Math.ceil(probe.height / 3);
  if (hits < totalSamples * 0.06 || maxX <= minX || maxY <= minY) return null;

  const padX = Math.round(probe.width * .04);
  const padY = Math.round(probe.height * .04);
  minX = Math.max(0, minX - padX); minY = Math.max(0, minY - padY);
  maxX = Math.min(probe.width - 1, maxX + padX); maxY = Math.min(probe.height - 1, maxY + padY);

  return { probe, x:minX, y:minY, w:maxX-minX+1, h:maxY-minY+1 };
}

async function saveWaybillSnapshot(code) {
  try {
    const c = document.createElement('canvas');
    let sourceW = 1280;
    let sourceH = 720;
    let source = null;

    if (currentCameraMode === 'phone' && els.phoneFrame.naturalWidth) {
      source = els.phoneFrame;
      sourceW = els.phoneFrame.naturalWidth;
      sourceH = els.phoneFrame.naturalHeight;
    } else if (els.video.readyState >= 2) {
      source = els.video;
      sourceW = els.video.videoWidth || sourceW;
      sourceH = els.video.videoHeight || sourceH;
    }

    if (!source) return null;

    const auto = autoCropWaybill(source, sourceW, sourceH);
    const ctx = c.getContext('2d');

    if (auto) {
      c.width = 1280;
      c.height = Math.max(500, Math.round(1280 * auto.h / auto.w));
      ctx.drawImage(auto.probe, auto.x, auto.y, auto.w, auto.h, 0, 0, c.width, c.height);
    } else {
      c.width = 1280;
      c.height = 720;
      drawZoomedSource(ctx, source, sourceW, sourceH, c.width, c.height, scannerZoom);
    }

    const blob = await new Promise((resolve) => c.toBlob(resolve, 'image/png'));
    if (!blob) return null;
    const arrayBuffer = await blob.arrayBuffer();

    const result = await ipcRenderer.invoke('snapshot:save', {
      code,
      capturedAt: Date.now(),
      buffer: arrayBuffer
    });

    return result;
  } catch (err) {
    console.error('Waybill snapshot error', err);
    return null;
  }
}

function addHistory(result, session) {
  const empty = els.historyBody.querySelector('.empty-row');
  if (empty) empty.remove();

  const tr = document.createElement('tr');
  const duration = formatDuration(new Date(result.endedAt) - new Date(result.startedAt));
  tr.innerHTML = `
    <td>${localTime(result.startedAt)}</td>
    <td><strong>${escapeHtml(result.code)}</strong></td>
    <td>${duration}</td>
    <td><button class="file-button" type="button">${escapeHtml(result.filename)}</button></td>
    <td class="storage-status">Local</td>
  `;
  const fileButton = tr.querySelector('.file-button');
  const statusCell = tr.querySelector('.storage-status');
  fileButton.dataset.path = result.path;
  fileButton.addEventListener('click', () => {
    ipcRenderer.invoke('file:show', fileButton.dataset.path);
  });
  historyFiles.set(result.path, { button: fileButton, statusCell });

  els.historyBody.prepend(tr);
  savedCount += 1;
  els.scanCount.textContent = `${savedCount} saved`;
  showToast(`${result.code} saved`);
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function beep(frequency = 700, duration = 80) {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    const ctx = new AudioCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = frequency;
    gain.gain.value = 0.04;
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    setTimeout(() => {
      osc.stop();
      ctx.close();
    }, duration);
  } catch {}
}


function beepSuccess() {
  beep(880, 85);
  setTimeout(() => beep(1180, 90), 95);
}



function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function updateSoftwareViews() {
  farViewZoom = clamp(Number(settings?.farViewZoom || 1), 1, 1.75);
  scannerZoom = clamp(Number(settings?.scannerZoom || 1.75), 1, 3);

  // The operator preview matches the wide/FAR evidence recording.
  const previewScale = `scale(${farViewZoom.toFixed(3)})`;
  els.video.style.transform = previewScale;
  els.phoneFrame.style.transform = previewScale;

  if (els.farViewZoomValue) els.farViewZoomValue.textContent = `${farViewZoom.toFixed(2)}×`;
  if (els.scannerZoomValue) els.scannerZoomValue.textContent = `${scannerZoom.toFixed(2)}×`;
}

function drawZoomedSource(ctx, source, srcW, srcH, dstW, dstH, zoom = 1) {
  const z = Math.max(1, Number(zoom || 1));
  const sw = srcW / z;
  const sh = srcH / z;
  const sx = (srcW - sw) / 2;
  const sy = (srcH - sh) / 2;
  ctx.drawImage(source, sx, sy, sw, sh, 0, 0, dstW, dstH);
}

async function applyContinuousAutofocus() {
  updateSoftwareViews();

  if (currentCameraMode !== 'local') {
    if (els.cameraFocusStatus) {
      els.cameraFocusStatus.textContent = 'Phone/network camera: use the phone camera autofocus. ScanCode keeps separate wide recording and zoomed scanner crops.';
    }
    return;
  }

  const track = els.video.srcObject?.getVideoTracks?.()[0];
  if (!track) return;

  let focusText = 'Camera default autofocus is active.';
  try {
    const caps = track.getCapabilities ? track.getCapabilities() : {};

    // Do NOT apply hardware zoom here. A hardware zoom would affect both the
    // recording and barcode scanner. ScanCode deliberately keeps one raw feed
    // and creates FAR + NEAR views in software.
    if (Array.isArray(caps.focusMode) && caps.focusMode.includes('continuous')) {
      await track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] });
      focusText = 'Continuous hardware autofocus enabled • one camera feed • FAR recording + NEAR scanner crop.';
    } else {
      focusText = 'Camera/driver controls autofocus • ScanCode still uses separate FAR recording and NEAR scanner crop.';
    }
  } catch {
    focusText = 'Autofocus is controlled by the camera/driver • software FAR/NEAR views remain active.';
  }

  if (els.cameraFocusStatus) els.cameraFocusStatus.textContent = focusText;
}

async function saveSoftwareViewSettings() {
  settings = await ipcRenderer.invoke('settings:update', {
    farViewZoom: clamp(Number(els.farViewZoom.value || 1), 1, 1.75),
    scannerZoom: clamp(Number(els.scannerZoom.value || 1.75), 1, 3)
  });
  updateSoftwareViews();
}

function drawRoundedRect(ctx, x, y, w, h, r) {
  const radius = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.arcTo(x + w, y, x + w, y + h, radius);
  ctx.arcTo(x + w, y + h, x, y + h, radius);
  ctx.arcTo(x, y + h, x, y, radius);
  ctx.arcTo(x, y, x + w, y, radius);
  ctx.closePath();
}

function activeSourceSize() {
  if (currentCameraMode === 'phone' && els.phoneFrame.naturalWidth) {
    return [els.phoneFrame.naturalWidth, els.phoneFrame.naturalHeight];
  }
  return [els.video.videoWidth || 1280, els.video.videoHeight || 720];
}

function fitCanvasToSource() {
  const [vw, vh] = activeSourceSize();
  if (els.canvas.width !== vw || els.canvas.height !== vh) {
    els.canvas.width = vw;
    els.canvas.height = vh;
  }
}

function drawOverlay() {
  const ctx = els.canvas.getContext('2d');
  fitCanvasToSource();
  const w = els.canvas.width;
  const h = els.canvas.height;

  if (currentCameraMode === 'phone' && els.phoneFrame.naturalWidth) {
    drawZoomedSource(ctx, els.phoneFrame, els.phoneFrame.naturalWidth, els.phoneFrame.naturalHeight, w, h, farViewZoom);
  } else if (els.video.readyState >= 2) {
    drawZoomedSource(ctx, els.video, els.video.videoWidth || w, els.video.videoHeight || h, w, h, farViewZoom);
  } else {
    ctx.fillStyle = '#050607';
    ctx.fillRect(0, 0, w, h);
  }

  if (currentSession) {
    const pad = Math.max(18, Math.round(w * 0.018));
    const panelW = Math.min(Math.round(w * 0.48), 660);
    const panelH = Math.min(Math.round(h * 0.30), 230);
    const x = pad;
    const y = h - panelH - pad;

    ctx.fillStyle = 'rgba(8, 10, 12, 0.82)';
    drawRoundedRect(ctx, x, y, panelW, panelH, 12);
    ctx.fill();

    ctx.fillStyle = '#ef5b5b';
    ctx.beginPath();
    ctx.arc(x + 22, y + 25, 7, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = '#ffffff';
    ctx.font = `700 ${Math.max(16, Math.round(w * 0.016))}px system-ui`;
    ctx.fillText('REC', x + 37, y + 32);

    ctx.fillStyle = '#aeb7c0';
    ctx.font = `600 ${Math.max(13, Math.round(w * 0.012))}px system-ui`;
    ctx.fillText(settings?.stationName || 'Station 01', x + panelW - 160, y + 31);

    ctx.fillStyle = '#ffffff';
    ctx.font = `800 ${Math.max(24, Math.round(w * 0.026))}px system-ui`;
    const code = activeDetails?.tracking || currentSession.code;
    ctx.fillText(shorten(ctx, code, panelW - 40), x + 20, y + 76);

    ctx.fillStyle = '#c6ced6';
    ctx.font = `600 ${Math.max(13, Math.round(w * 0.013))}px system-ui`;
    const order = activeDetails?.order || 'Looking up…';
    const courier = activeDetails?.courier || '—';
    const item = activeDetails?.item || '—';
    ctx.fillText(shorten(ctx, `Order: ${order}`, panelW - 40), x + 20, y + 110);
    ctx.fillText(shorten(ctx, `Courier: ${courier}`, panelW - 40), x + 20, y + 140);
    ctx.fillText(shorten(ctx, `Item: ${item}`, panelW - 40), x + 20, y + 170);

    const nowText = new Date().toLocaleString();
    ctx.fillStyle = '#929ca6';
    ctx.font = `500 ${Math.max(11, Math.round(w * 0.0105))}px system-ui`;
    ctx.fillText(nowText, x + 20, y + panelH - 18);

    if (settings?.operatorName) {
      ctx.textAlign = 'right';
      ctx.fillText(`Operator: ${settings.operatorName}`, x + panelW - 20, y + panelH - 18);
      ctx.textAlign = 'left';
    }
  }

  animationId = requestAnimationFrame(drawOverlay);
}

function shorten(ctx, text, maxWidth) {
  const raw = String(text || '');
  if (ctx.measureText(raw).width <= maxWidth) return raw;
  let out = raw;
  while (out.length > 4 && ctx.measureText(out + '…').width > maxWidth) out = out.slice(0, -1);
  return out + '…';
}

function updateTimer() {
  if (!currentSession) {
    els.timer.textContent = '00:00';
    return;
  }
  els.timer.textContent = formatDuration(Date.now() - currentSession.startedAt);
}


function evaluateCameraQuality() {
  if (settings?.cameraQualityEnabled === false) {
    badge(els.qualityBadge, 'QUALITY OFF', 'neutral');
    return;
  }

  let source = null, sw = 0, sh = 0;
  if (currentCameraMode === 'phone' && els.phoneFrame.naturalWidth) {
    source = els.phoneFrame; sw = els.phoneFrame.naturalWidth; sh = els.phoneFrame.naturalHeight;
  } else if (els.video.readyState >= 2) {
    source = els.video; sw = els.video.videoWidth; sh = els.video.videoHeight;
  }
  if (!source || !sw || !sh) {
    badge(els.qualityBadge, 'QUALITY —', 'neutral');
    return;
  }

  const c = document.createElement('canvas');
  c.width = 192; c.height = 108;
  const ctx = c.getContext('2d', { willReadFrequently:true });
  drawZoomedSource(ctx, source, sw, sh, c.width, c.height, 1);
  const data = ctx.getImageData(0,0,c.width,c.height).data;

  let lumSum = 0, edgeSum = 0, samples = 0;
  const gray = new Float32Array(c.width * c.height);
  for (let y=0; y<c.height; y++) {
    for (let x=0; x<c.width; x++) {
      const i=(y*c.width+x)*4;
      const g=data[i]*.299+data[i+1]*.587+data[i+2]*.114;
      gray[y*c.width+x]=g;
      lumSum += g; samples++;
    }
  }
  for (let y=1; y<c.height; y++) {
    for (let x=1; x<c.width; x++) {
      const g=gray[y*c.width+x];
      edgeSum += Math.abs(g-gray[y*c.width+x-1]) + Math.abs(g-gray[(y-1)*c.width+x]);
    }
  }
  const lum = lumSum / Math.max(1,samples);
  const edge = edgeSum / Math.max(1,(c.width-1)*(c.height-1)*2);

  if (lum < 42) badge(els.qualityBadge, 'TOO DARK', 'bad');
  else if (lum > 225) badge(els.qualityBadge, 'TOO BRIGHT', 'warning');
  else if (edge < 6.5) badge(els.qualityBadge, 'CHECK FOCUS', 'warning');
  else badge(els.qualityBadge, 'QUALITY GOOD', 'good');
}

function startQualityTimer() {
  if (qualityTimer) clearInterval(qualityTimer);
  evaluateCameraQuality();
  qualityTimer = setInterval(evaluateCameraQuality, 1200);
}


function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

async function promiseWithTimeout(promise, ms, label = 'Operation') {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(() => {
          const err = new Error(`${label} timed out after ${Math.round(ms/1000)} seconds.`);
          err.name = 'TimeoutError';
          reject(err);
        }, ms);
      })
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function getUserMediaWithTimeout(constraints, ms = 7000) {
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

async function waitForVideoReady(video, ms = 6000) {
  if (video.readyState >= 1) return;
  await promiseWithTimeout(new Promise((resolve, reject) => {
    const onReady = () => { cleanup(); resolve(); };
    const onError = () => { cleanup(); reject(video.error || new Error('Video element failed.')); };
    const cleanup = () => {
      video.removeEventListener('loadedmetadata', onReady);
      video.removeEventListener('error', onError);
    };
    video.addEventListener('loadedmetadata', onReady, { once:true });
    video.addEventListener('error', onError, { once:true });
  }), ms, 'Camera preview');
}

async function loadCameraList(preferredDeviceId = '') {
  if (!navigator.mediaDevices?.enumerateDevices) {
    els.cameraSelect.innerHTML = '<option value="">Camera list unavailable</option>';
    els.cameraSelect.disabled = true;
    return [];
  }

  let devices = [];
  try {
    devices = await navigator.mediaDevices.enumerateDevices();
  } catch (err) {
    console.error('Camera enumeration failed', err);
  }

  const cameras = devices.filter(d => d.kind === 'videoinput');
  const old = preferredDeviceId || els.cameraSelect.value;
  els.cameraSelect.innerHTML = '';

  if (!cameras.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'Default / Built-in Camera';
    els.cameraSelect.appendChild(opt);
    els.cameraSelect.disabled = false;
    return [];
  }

  els.cameraSelect.disabled = false;
  cameras.forEach((cam, i) => {
    const opt = document.createElement('option');
    opt.value = cam.deviceId;
    opt.textContent = cam.label?.trim() || (i === 0 ? 'Built-in / Camera 1' : `Camera ${i + 1}`);
    els.cameraSelect.appendChild(opt);
  });

  if (old && cameras.some(c => c.deviceId === old)) els.cameraSelect.value = old;
  else els.cameraSelect.selectedIndex = 0;

  return cameras;
}

function stopLocalCamera() {
  stopLocalZoomScanner();
  if (scannerControls) {
    try { scannerControls.stop(); } catch {}
    scannerControls = null;
  }
  if (localCameraStream) {
    for (const track of localCameraStream.getTracks()) {
      try { track.stop(); } catch {}
    }
    localCameraStream = null;
  }
  if (els.video.srcObject) {
    try {
      for (const track of els.video.srcObject.getTracks?.() || []) track.stop();
    } catch {}
    els.video.srcObject = null;
  }
}

function stopPhoneMode() {
  if (phonePollTimer) clearInterval(phonePollTimer);
  if (phoneScanTimer) clearInterval(phoneScanTimer);
  phonePollTimer = null; phoneScanTimer = null;
  els.phoneFrame.style.display = 'none';
  els.video.style.display = 'block';
  els.phoneBridgePanel.classList.add('hidden');
  ipcRenderer.invoke('network-camera:stop').catch(() => {});
}

async function pollPhoneFrame() {
  const result = await ipcRenderer.invoke('network-camera:get-frame');
  if (result?.lastFrameAt) lastPhoneFrameAt = Number(result.lastFrameAt);
  if (result?.bytes?.length) {
    const blob = new Blob([result.bytes], { type: 'image/jpeg' });
    const nextUrl = URL.createObjectURL(blob);
    els.phoneFrame.onload = () => {
      if (phoneBlobUrl) URL.revokeObjectURL(phoneBlobUrl);
      phoneBlobUrl = nextUrl;
      els.cameraMessage.classList.add('hidden');
      badge(els.cameraBadge, 'PHONE LIVE', 'good');
    };
    els.phoneFrame.src = nextUrl;
  } else if (!result?.connected) {
    badge(els.cameraBadge, result?.state === 'error' ? 'NETWORK CAMERA ERROR' : 'WAITING CAMERA', result?.state === 'error' ? 'bad' : 'warning');
  }
}

async function scanPhoneFrame() {
  if (phoneScanning || !els.phoneFrame.naturalWidth) return;
  phoneScanning = true;
  try {
    const c = els.scanCanvas, ctx = c.getContext('2d');
    c.width = els.phoneFrame.naturalWidth; c.height = els.phoneFrame.naturalHeight;
    drawZoomedSource(ctx, els.phoneFrame, els.phoneFrame.naturalWidth, els.phoneFrame.naturalHeight, c.width, c.height, scannerZoom);
    const result = await (canvasCodeReader || codeReader).decodeFromCanvas(c);
    if (result) processDetectedResult(result, 'phone');
  } catch (e) {
    // Not-found errors are expected between successful scans.
  } finally { phoneScanning = false; }
}


async function scanLocalZoomedFrame() {
  if (localFrameScanning || currentCameraMode !== 'local' || els.video.readyState < 2) return;
  localFrameScanning = true;
  try {
    const c = els.scanCanvas;
    const ctx = c.getContext('2d');
    c.width = els.video.videoWidth || 1280;
    c.height = els.video.videoHeight || 720;
    drawZoomedSource(ctx, els.video, els.video.videoWidth || c.width, els.video.videoHeight || c.height, c.width, c.height, scannerZoom);
    const result = await (canvasCodeReader || codeReader).decodeFromCanvas(c);
    if (result) processDetectedResult(result, 'camera');
  } catch (e) {
    // A frame without a barcode is normal.
  } finally {
    localFrameScanning = false;
  }
}

function startLocalZoomScanner() {
  if (localScanTimer) clearInterval(localScanTimer);
  localScanTimer = setInterval(scanLocalZoomedFrame, 260);
}

function stopLocalZoomScanner() {
  if (localScanTimer) clearInterval(localScanTimer);
  localScanTimer = null;
  localFrameScanning = false;
}

async function startPhoneMode() {
  stopLocalCamera();
  if (scannerControls) { try { scannerControls.stop(); } catch {} scannerControls = null; }
  currentCameraMode = 'phone';
  els.video.style.display = 'none'; els.phoneFrame.style.display = 'block';
  els.phoneBridgePanel.classList.remove('hidden');
  els.cameraMessage.textContent = 'Waiting for phone camera…';
  els.cameraMessage.classList.remove('hidden');
  badge(els.cameraBadge, 'WAITING CAMERA', 'warning');
  codeReader = new BrowserMultiFormatReader();
  canvasCodeReader = new BrowserMultiFormatReader();
  await applyContinuousAutofocus()
  els.phoneUrls.textContent = 'Enter the camera URL, then Connect. USB/virtual cameras are available in PC / USB / Virtual Camera mode.';
  if (els.networkCameraUrl.value.trim()) await ipcRenderer.invoke('network-camera:start', els.networkCameraUrl.value.trim());
  await pollPhoneFrame();
  phonePollTimer = setInterval(pollPhoneFrame, 140);
  phoneScanTimer = setInterval(scanPhoneFrame, 240);
}

async function startSelectedCamera() {
  currentCameraMode = els.cameraMode.value || 'local';
  stopPhoneMode();
  if (currentCameraMode === 'phone') return startPhoneMode();
  return startCamera();
}

async function startCamera(requestedDeviceId = '') {
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

async function saveSettingsFromUi() {
  settings = await ipcRenderer.invoke('settings:update', {
    stationName: els.stationName.value.trim() || 'Station 01',
    operatorName: els.operatorName.value.trim(),
    overlapMs: Number(els.overlapMs.value || 900),
    serverFolder: els.serverFolder.value.trim(),
    autoSyncEnabled: Boolean(els.autoSyncEnabled.checked),
    successSoundEnabled: Boolean(els.successSoundEnabled.checked),
    cameraMode: els.cameraMode.value || 'local',
    networkCameraUrl: els.networkCameraUrl.value.trim(),
    farViewZoom: Number(els.farViewZoom.value || settings?.farViewZoom || 1),
    scannerZoom: Number(els.scannerZoom.value || settings?.scannerZoom || 1.75),
    autoStartWithWindows: Boolean(els.autoStartWithWindows.checked),
    cameraQualityEnabled: Boolean(els.cameraQualityEnabled.checked),
    scanConfirmations: Number(els.scanConfirmations.value || 2),
    barcodeFilter: els.barcodeFilter.value || 'shipping',
    bigSellerAutoSubmit: Boolean(els.bigSellerAutoSubmit.checked),
    bigSellerUrl: els.bigSellerUrl.value.trim()
  });
  renderSettings();
}

function renderSettings() {
  els.stationName.value = settings.stationName || 'Station 01';
  els.operatorName.value = settings.operatorName || '';
  els.overlapMs.value = String(settings.overlapMs || 900);
  els.folderPath.textContent = settings.recordingFolder || '—';
  els.serverFolder.value = settings.serverFolder || '';
  els.autoSyncEnabled.checked = settings.autoSyncEnabled !== false;
  els.successSoundEnabled.checked = settings.successSoundEnabled !== false;
  els.cameraMode.value = settings.cameraMode || 'local';
  els.networkCameraUrl.value = settings.networkCameraUrl || '';
  els.farViewZoom.value = String(settings.farViewZoom || 1);
  els.scannerZoom.value = String(settings.scannerZoom || 1.75);
  farViewZoom = Number(settings.farViewZoom || 1);
  scannerZoom = Number(settings.scannerZoom || 1.75);
  els.autoStartWithWindows.checked = settings.autoStartWithWindows !== false;
  els.cameraQualityEnabled.checked = settings.cameraQualityEnabled !== false;
  els.scanConfirmations.value = String(settings.scanConfirmations || 2);
  els.barcodeFilter.value = settings.barcodeFilter || 'shipping';
  els.bigSellerAutoSubmit.checked = settings.bigSellerAutoSubmit !== false;
  els.bigSellerUrl.value = settings.bigSellerUrl || '';
  updateSoftwareViews();
  const d = new Date();
  const ds = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  els.todayFolder.textContent = `Today: ${settings.recordingFolder}\\${ds}`;
}

function renderSyncStatus(status = {}) {
  const state = status.state || 'not-configured';
  const message = status.message || 'SERVER NOT SET';

  if (state === 'online') badge(els.syncBadge, message, 'good');
  else if (state === 'syncing') badge(els.syncBadge, message, 'warning');
  else if (state === 'offline' || state === 'warning') badge(els.syncBadge, message, 'bad');
  else badge(els.syncBadge, message, 'neutral');

  if (els.syncStatusText) {
    const detail = state === 'offline'
      ? 'Server is unavailable. Videos remain safely in Documents\\ScanCode and will retry automatically.'
      : state === 'syncing'
        ? 'Transferring parcel evidence files to the central server…'
        : state === 'online'
          ? 'Server is reachable. Verified video, waybill and metadata files are removed from this scanner PC after transfer.'
          : state === 'disabled'
            ? 'Automatic server transfer is turned off.'
            : 'Set a server shared folder to enable automatic transfer.';
    els.syncStatusText.textContent = detail;
  }

  for (const moved of (status.transferred || [])) {
    const row = historyFiles.get(moved.localFile);
    if (row) {
      row.button.dataset.path = moved.serverFile;
      row.statusCell.textContent = 'Server';
      historyFiles.delete(moved.localFile);
      historyFiles.set(moved.serverFile, row);
    }
  }
}

ipcRenderer.on('sync:status', (event, status) => renderSyncStatus(status));

async function init() {
  settings = await ipcRenderer.invoke('settings:get');
  renderSettings();

  if (!navigator.mediaDevices?.getUserMedia) {
    els.cameraMessage.textContent = 'Camera API is unavailable. Manual test still works.';
    badge(els.cameraBadge, 'CAMERA UNSUPPORTED', 'bad');
    els.cameraSelect.innerHTML = '<option value="">Camera unavailable</option>';
    els.cameraSelect.disabled = true;
  } else {
    // Always boot into the PC / USB / built-in webcam path. Phone/network
    // camera mode is opt-in per session so an old saved network URL cannot
    // prevent a laptop's built-in camera from starting after relaunch.
    settings.cameraMode = 'local';
    els.cameraMode.value = 'local';
    settings = await ipcRenderer.invoke('settings:update', { cameraMode: 'local' });
    els.cameraSelect.innerHTML = '<option value="">Default / Built-in Camera</option>';
    // Let the secure renderer finish its first paint before requesting the webcam.
    await sleep(300);
    await startCamera('');
  }

  drawOverlay();
  timerId = setInterval(updateTimer, 250);
  startQualityTimer();
  renderSyncStatus(await ipcRenderer.invoke('sync:now'));
}

els.manualScanBtn.addEventListener('click', () => {
  const code = cleanCode(els.manualCode.value);
  if (!code) return;
  handleScan(code, 'manual');
  els.manualCode.value = '';
  els.manualCode.focus();
});

els.manualCode.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') els.manualScanBtn.click();
});

els.diagnoseCameraBtn?.addEventListener('click', async () => {
  const sys = await ipcRenderer.invoke('camera:system-status').catch(() => null);
  let deviceText = 'Device enumeration unavailable';
  try {
    const devices = await promiseWithTimeout(navigator.mediaDevices.enumerateDevices(), 3000, 'Device enumeration');
    const cams = devices.filter(d => d.kind === 'videoinput');
    deviceText = cams.length
      ? `${cams.length} camera(s): ${cams.map((c,i) => c.label || `Camera ${i+1}`).join(', ')}`
      : '0 cameras reported by Chromium';
  } catch (err) {
    deviceText = `Camera enumeration failed: ${err?.message || err}`;
  }
  const message = `Windows access: ${sys?.cameraAccess || 'unknown'} | ${deviceText} | Pipeline: ZXing direct webcam | Electron ${sys?.electron || '?'}`;
  els.cameraMessage.textContent = message;
  els.cameraMessage.classList.remove('hidden');
  showToast(message);
});

els.restartCameraBtn.addEventListener('click', async () => {
  cameraLastFailureAt = 0;
  showToast('Restarting camera…');
  if (els.cameraMode.value === 'local') await startCamera(els.cameraSelect.value || '');
  else await startPhoneMode();
});

els.cameraSelect.addEventListener('change', async () => {
  if (els.cameraMode.value === 'local') {
    showToast(`Camera selected: ${els.cameraSelect.options[els.cameraSelect.selectedIndex]?.text || 'Camera'}`);
    await startCamera(els.cameraSelect.value);
  }
});
els.cameraMode.addEventListener('change', async () => { await saveSettingsFromUi(); await startSelectedCamera(); });

navigator.mediaDevices?.addEventListener?.('devicechange', async () => {
  if (currentCameraMode !== 'local' || cameraStarting) return;
  const activeId = localCameraStream?.getVideoTracks?.()[0]?.getSettings?.().deviceId || els.cameraSelect.value;
  await loadCameraList(activeId);
});
els.successSoundEnabled.addEventListener('change', saveSettingsFromUi);
els.testSoundBtn.addEventListener('click', beepSuccess);
els.connectNetworkCameraBtn.addEventListener('click', async () => {
  const url = els.networkCameraUrl.value.trim();
  if (!url) { showToast('Enter a phone/network camera URL first.'); return; }
  els.cameraMode.value = 'phone';
  await saveSettingsFromUi();
  const result = await ipcRenderer.invoke('network-camera:start', url);
  if (result?.ok === false) { showToast(result?.error || 'Network camera connection failed.'); return; }
  await startPhoneMode();
  showToast('Connecting phone/network camera…');
});



els.farViewZoom?.addEventListener('input', () => {
  farViewZoom = Number(els.farViewZoom.value);
  els.farViewZoomValue.textContent = `${farViewZoom.toFixed(2)}×`;
  updateSoftwareViews();
});
els.farViewZoom?.addEventListener('change', saveSoftwareViewSettings);

els.scannerZoom?.addEventListener('input', () => {
  scannerZoom = Number(els.scannerZoom.value);
  els.scannerZoomValue.textContent = `${scannerZoom.toFixed(2)}×`;
});
els.scannerZoom?.addEventListener('change', saveSoftwareViewSettings);

els.stationName.addEventListener('change', saveSettingsFromUi);
els.operatorName.addEventListener('change', saveSettingsFromUi);
els.overlapMs.addEventListener('change', saveSettingsFromUi);
els.serverFolder.addEventListener('change', async () => {
  await saveSettingsFromUi();
  renderSyncStatus(await ipcRenderer.invoke('sync:now'));
});
els.autoSyncEnabled.addEventListener('change', async () => {
  await saveSettingsFromUi();
  renderSyncStatus(await ipcRenderer.invoke('sync:now'));
});

els.openFolderBtn.addEventListener('click', () => ipcRenderer.invoke('folder:open-recordings'));

els.chooseServerFolderBtn.addEventListener('click', async () => {
  settings = await ipcRenderer.invoke('settings:choose-server-folder');
  renderSettings();
  renderSyncStatus(await ipcRenderer.invoke('sync:now'));
});

els.syncNowBtn.addEventListener('click', async () => {
  renderSyncStatus({ state: 'syncing', message: 'CHECKING SERVER…' });
  renderSyncStatus(await ipcRenderer.invoke('sync:now'));
});

els.openServerBtn.addEventListener('click', async () => {
  const result = await ipcRenderer.invoke('folder:open-server');
  if (!result?.ok) showToast(result?.error || 'Server folder unavailable.');
});


els.markExceptionBtn.addEventListener('click', () => {
  if (!currentSession) {
    showToast('Scan a parcel first.');
    return;
  }
  const type = els.exceptionType.value;
  currentSession.exception = type || null;
  els.exceptionStatus.textContent = type ? `Exception marked: ${type}` : 'No exception on current parcel.';
  els.exceptionStatus.classList.toggle('active', Boolean(type));
  showToast(type ? 'Exception saved to parcel evidence.' : 'Exception cleared.');
});

els.openBigSellerBtn.addEventListener('click', async () => {
  await saveSettingsFromUi();
  if (!els.bigSellerUrl.value.trim()) {
    els.bigSellerStatus.textContent = 'NEEDS SETUP — enter the exact BigSeller warehouse page URL first.';
    showToast('BigSeller URL is required.');
    return;
  }
  const r = await ipcRenderer.invoke('bigseller:open');
  els.bigSellerStatus.textContent = r?.ok
    ? 'PASS — BigSeller bridge opened. Scan a test parcel to verify the exact input field.'
    : (r?.error || 'FAIL — could not open BigSeller bridge.');
});

for (const el of [els.bigSellerAutoSubmit, els.autoStartWithWindows, els.cameraQualityEnabled, els.scanConfirmations, els.barcodeFilter]) {
  el?.addEventListener('change', async () => {
    await saveSettingsFromUi();
    evaluateCameraQuality();
  });
}
els.bigSellerUrl.addEventListener('change', saveSettingsFromUi);

els.endShiftBtn.addEventListener('click', async () => {
  els.shiftStatus.textContent = 'Checking server and local queue…';
  const r = await ipcRenderer.invoke('shift:verify');
  if (r?.ok) {
    els.shiftStatus.textContent = '✓ Shift clear: server online, no pending videos, no recovery files.';
    showToast('End-of-shift verification passed.');
  } else {
    els.shiftStatus.textContent =
      `Needs attention — Server: ${r?.serverOnline ? 'ONLINE' : 'OFFLINE'} • Pending videos: ${r?.pendingVideos ?? 0} • Pending evidence files: ${r?.pendingEvidenceFiles ?? 0} • Recovery files: ${r?.recoveryFiles ?? 0}`;
    showToast('End-of-shift check found pending items.');
  }
});

async function runServerSearch() {
  const q = cleanCode(els.serverSearchInput.value);
  if (!q) return;
  els.serverSearchResults.textContent = 'Searching server…';
  els.serverVideoPlayer.style.display = 'none';
  els.serverWaybillPreview.style.display = 'none';
  const r = await ipcRenderer.invoke('evidence:search', q);
  if (!r?.ok) {
    els.serverSearchResults.textContent = r?.error || 'Search failed.';
    return;
  }
  if (!r.results?.length) {
    els.serverSearchResults.textContent = 'No matching evidence found on the server.';
    return;
  }

  els.serverSearchResults.innerHTML = '';
  for (const item of r.results) {
    const row = document.createElement('div');
    row.className = 'search-result-item';
    row.innerHTML = `
      <div><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.day || '')}</small></div>
      <div class="search-result-actions">
        <button class="btn secondary open-evidence">Open</button>
        ${item.ext === '.webm' || item.ext === '.mp4' ? '<button class="btn primary play-evidence">Play</button>' : ''}
        ${item.ext === '.png' ? '<button class="btn primary view-waybill">View</button>' : ''}
      </div>
    `;
    row.querySelector('.open-evidence').addEventListener('click', () => ipcRenderer.invoke('file:show', item.path));
    row.querySelector('.play-evidence')?.addEventListener('click', () => {
      els.serverVideoPlayer.src = item.url;
      els.serverVideoPlayer.style.display = 'block';
      els.serverVideoPlayer.play().catch(() => {});
    });
    row.querySelector('.view-waybill')?.addEventListener('click', () => {
      els.serverWaybillPreview.src = item.url;
      els.serverWaybillPreview.style.display = 'block';
    });
    els.serverSearchResults.appendChild(row);
  }
}

els.serverSearchBtn.addEventListener('click', runServerSearch);
els.serverSearchInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') runServerSearch();
});

ipcRenderer.on('recovery:status', (event, status) => {
  const count = status?.recovered?.length || 0;
  if (count) showToast(`${count} interrupted recording(s) recovered.`);
});

ipcRenderer.on('watchdog:tick', async () => {
  if (watchdogRestarting || cameraStarting) return;
  if (cameraLastFailureAt && Date.now() - cameraLastFailureAt < 30000) return;

  if (currentCameraMode === 'local' && els.video.readyState >= 2) {
    const t = els.video.currentTime;
    if (Math.abs(t - lastVideoTime) > .02) {
      lastVideoTime = t;
      lastVideoAdvancedAt = Date.now();
      return;
    }
    if (Date.now() - lastVideoAdvancedAt < 9000) return;
  } else if (currentCameraMode === 'phone') {
    if (els.phoneFrame.naturalWidth && Date.now() - lastPhoneFrameAt < 9000) return;
  } else {
    if (Date.now() - lastVideoAdvancedAt < 9000) return;
  }

  watchdogRestarting = true;
  showToast('Camera watchdog restarting feed…');
  try { await startSelectedCamera(); } catch {}
  lastVideoAdvancedAt = Date.now();
  watchdogRestarting = false;
});



els.startVideoBtn?.addEventListener('click', startOrResumeRecording);
els.pauseVideoBtn?.addEventListener('click', pauseCurrentRecording);
els.stopVideoBtn?.addEventListener('click', async () => {
  if (!currentSession) {
    showToast('No active recording.');
    return;
  }
  const toStop = currentSession;
  currentSession = null;
  activeDetails = null;
  els.currentCode.textContent = 'Waiting for scan';
  setDetails(null);
  badge(els.lookupState, 'IDLE', 'neutral');
  els.exceptionType.value = '';
  els.exceptionStatus.textContent = 'No exception on current parcel.';
  els.exceptionStatus.classList.remove('active');
  updateRecordingUi();
  await stopAndSaveSession(toStop, 'manual-stop');
  showToast('Recording stopped and saved.');
});





window.addEventListener('keydown', async (event) => {
  if (event.repeat) return;
  if (event.key === 'F1') { event.preventDefault(); await startOrResumeRecording(); return; }
  if (event.key === 'F2') { event.preventDefault(); await pauseCurrentRecording(); return; }
  if (event.key === 'F3') { event.preventDefault(); els.stopVideoBtn?.click(); return; }
});

window.addEventListener('beforeunload', () => {
  stopLocalCamera()
  cancelAnimationFrame(animationId);
  clearInterval(timerId);
  if (qualityTimer) clearInterval(qualityTimer);
  if (phonePollTimer) clearInterval(phonePollTimer);
  if (phoneScanTimer) clearInterval(phoneScanTimer);
  if (phoneBlobUrl) URL.revokeObjectURL(phoneBlobUrl);
});


window.addEventListener('error', (event) => {
  console.error('ScanCode runtime error:', event.error || event.message);
  showToast(`Error: ${event.message || 'unexpected runtime error'}`);
});
window.addEventListener('unhandledrejection', (event) => {
  console.error('ScanCode unhandled rejection:', event.reason);
  showToast(`Error: ${event.reason?.message || event.reason || 'operation failed'}`);
});

init().catch((err) => { console.error(err); showToast(`Startup failed: ${err?.message || err}`); });

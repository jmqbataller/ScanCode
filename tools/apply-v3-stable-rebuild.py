from pathlib import Path
import json, re

ROOT = Path(__file__).resolve().parents[1]

# ---------------- main.js patches ----------------
main_path = ROOT / 'main.js'
main = main_path.read_text(encoding='utf-8')

if "const SMOKE_TEST = process.argv.includes('--smoke-test');" not in main:
    anchor = "const { pathToFileURL } = require('url');\n"
    insert = """const { pathToFileURL } = require('url');

const SMOKE_TEST = process.argv.includes('--smoke-test');
if (SMOKE_TEST) {
  app.commandLine.appendSwitch('use-fake-device-for-media-stream');
  app.commandLine.appendSwitch('use-fake-ui-for-media-stream');
  app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');
}
"""
    if anchor not in main:
        raise RuntimeError('main.js import anchor missing')
    main = main.replace(anchor, insert, 1)

# Make runtime smoke tests non-interactive and stop background throttling.
main = main.replace("    title: 'ScanCode',\n    webPreferences: {", "    title: 'ScanCode',\n    show: !SMOKE_TEST,\n    webPreferences: {", 1)
main = main.replace("      contextIsolation: false\n", "      contextIsolation: false,\n      backgroundThrottling: false\n", 1)

# Complete media permission handling. Keep local file renderer because that was
# the last known-working path on the user's HP TrueVision webcam.
req_block = """  // Known-working camera permission flow from ScanCode v1.3.
  // Chromium still asks Electron before opening a webcam; allow media for the
  // local ScanCode renderer.
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    callback(permission === 'media');
  });
"""
new_block = """  // ScanCode is a local desktop app. Allow only media permission through
  // Electron's explicit permission handlers so webcam access is deterministic.
  session.defaultSession.setPermissionCheckHandler((webContents, permission) => permission === 'media');
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    callback(permission === 'media');
  });
"""
if req_block in main:
    main = main.replace(req_block, new_block, 1)
elif 'setPermissionCheckHandler' not in main:
    ready_anchor = "app.whenReady().then(() => {\n"
    if ready_anchor not in main:
        raise RuntimeError('app ready anchor missing')
    main = main.replace(ready_anchor, ready_anchor + new_block, 1)

# Runtime smoke-test IPC. This makes CI test the real Electron renderer, camera
# pipeline and MediaRecorder save path before a release is accepted.
if "ipcMain.handle('smoke:is-enabled'" not in main:
    anchor = "ipcMain.handle('camera:system-status', () => {"
    smoke = """ipcMain.handle('smoke:is-enabled', () => SMOKE_TEST);
ipcMain.handle('smoke:pass', async (event, payload = {}) => {
  if (!SMOKE_TEST) return { ok:false };
  const out = path.join(process.cwd(), 'SMOKE_RUNTIME_OK.txt');
  fs.writeFileSync(out, `PASS\\n${new Date().toISOString()}\\n${JSON.stringify(payload, null, 2)}\\n`, 'utf8');
  setTimeout(() => app.exit(0), 150);
  return { ok:true, path:out };
});
ipcMain.handle('smoke:fail', async (event, message) => {
  if (!SMOKE_TEST) return { ok:false };
  const out = path.join(process.cwd(), 'SMOKE_RUNTIME_FAIL.txt');
  fs.writeFileSync(out, `FAIL\\n${new Date().toISOString()}\\n${String(message || 'Unknown smoke-test failure')}\\n`, 'utf8');
  setTimeout(() => app.exit(1), 150);
  return { ok:true, path:out };
});

"""
    if anchor not in main:
        raise RuntimeError('camera status IPC anchor missing')
    main = main.replace(anchor, smoke + anchor, 1)

main_path.write_text(main, encoding='utf-8')

# ---------------- renderer.js full stable rebuild ----------------
renderer = r'''const { ipcRenderer } = require('electron');
const { BrowserMultiFormatReader, BrowserCodeReader } = require('@zxing/browser');
const { BarcodeFormat } = require('@zxing/library');

const $ = (id) => document.getElementById(id);
const els = {
  video: $('video'), videoStage: $('videoStage'), recordingOverlay: $('recordingOverlay'),
  phoneFrame: $('phoneFrame'), scanCanvas: $('scanCanvas'), canvas: $('recordCanvas'),
  cameraMode: $('cameraMode'), cameraMessage: $('cameraMessage'), cameraSelect: $('cameraSelect'),
  phoneBridgePanel: $('phoneBridgePanel'), phoneUrls: $('phoneUrls'), networkCameraUrl: $('networkCameraUrl'),
  farViewZoom: $('farViewZoom'), farViewZoomValue: $('farViewZoomValue'), scannerZoom: $('scannerZoom'),
  scannerZoomValue: $('scannerZoomValue'), cameraFocusStatus: $('cameraFocusStatus'),
  connectNetworkCameraBtn: $('connectNetworkCameraBtn'), restartCameraBtn: $('restartCameraBtn'),
  diagnoseCameraBtn: $('diagnoseCameraBtn'), cameraBadge: $('cameraBadge'), qualityBadge: $('qualityBadge'),
  syncBadge: $('syncBadge'), recordBadge: $('recordBadge'), currentCode: $('currentCode'), timer: $('timer'),
  recDot: $('recDot'), manualCode: $('manualCode'), manualScanBtn: $('manualScanBtn'), lookupState: $('lookupState'),
  detailTracking: $('detailTracking'), detailOrder: $('detailOrder'), detailCourier: $('detailCourier'),
  detailCustomer: $('detailCustomer'), detailItem: $('detailItem'), detailQty: $('detailQty'), detailStatus: $('detailStatus'),
  stationName: $('stationName'), operatorName: $('operatorName'), overlapMs: $('overlapMs'),
  successSoundEnabled: $('successSoundEnabled'), testSoundBtn: $('testSoundBtn'), todayFolder: $('todayFolder'),
  openFolderBtn: $('openFolderBtn'), folderPath: $('folderPath'), serverFolder: $('serverFolder'),
  autoSyncEnabled: $('autoSyncEnabled'), chooseServerFolderBtn: $('chooseServerFolderBtn'), syncNowBtn: $('syncNowBtn'),
  openServerBtn: $('openServerBtn'), syncStatusText: $('syncStatusText'), exceptionType: $('exceptionType'),
  markExceptionBtn: $('markExceptionBtn'), exceptionStatus: $('exceptionStatus'), bigSellerAutoSubmit: $('bigSellerAutoSubmit'),
  bigSellerUrl: $('bigSellerUrl'), openBigSellerBtn: $('openBigSellerBtn'), bigSellerStatus: $('bigSellerStatus'),
  autoStartWithWindows: $('autoStartWithWindows'), cameraQualityEnabled: $('cameraQualityEnabled'),
  scanConfirmations: $('scanConfirmations'), barcodeFilter: $('barcodeFilter'), endShiftBtn: $('endShiftBtn'),
  shiftStatus: $('shiftStatus'), serverSearchInput: $('serverSearchInput'), serverSearchBtn: $('serverSearchBtn'),
  serverSearchResults: $('serverSearchResults'), serverVideoPlayer: $('serverVideoPlayer'),
  serverWaybillPreview: $('serverWaybillPreview'), startVideoBtn: $('startVideoBtn'), pauseVideoBtn: $('pauseVideoBtn'),
  stopVideoBtn: $('stopVideoBtn'), transportStatus: $('transportStatus'), historyBody: $('historyBody'),
  scanCount: $('scanCount'), toast: $('toast')
};

let settings = null;
let cameraReader = null;
let cameraControls = null;
let cameraStream = null;
let canvasReader = new BrowserMultiFormatReader();
let currentCameraMode = 'local';
let cameraStarting = false;
let phonePollTimer = null;
let phoneScanTimer = null;
let phoneBlobUrl = null;
let phoneScanning = false;
let currentSession = null;
let activeDetails = null;
let animationId = null;
let timerId = null;
let qualityTimer = null;
let savedCount = 0;
let scanBusy = false;
let lastAccepted = { code:null, at:0 };
let scanCandidate = { code:null, format:null, count:0, at:0 };
let farViewZoom = 1;
let scannerZoom = 1.75;
let lastFrameAt = Date.now();
let lastVideoTime = -1;
let watchdogRestarting = false;
const historyFiles = new Map();
const SCAN_DEBOUNCE_MS = 1400;

const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const cleanCode = (v) => String(v || '').trim().replace(/[\r\n]+/g, '');
const clamp = (v, min, max) => Math.min(max, Math.max(min, Number(v)));

function showToast(message) {
  if (!els.toast) return;
  els.toast.textContent = String(message || '');
  els.toast.classList.add('show');
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => els.toast.classList.remove('show'), 2600);
}
function badge(el, text, state='neutral') {
  if (!el) return;
  el.textContent = text;
  el.className = `${el.classList.contains('mini-state') ? 'mini-state' : 'badge'} ${state}`;
}
function formatDuration(ms) {
  const total = Math.max(0, Math.floor(ms/1000));
  return `${String(Math.floor(total/60)).padStart(2,'0')}:${String(total%60).padStart(2,'0')}`;
}
function escapeHtml(v) {
  return String(v ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');
}
function beep(freq=900, duration=80) {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const ctx = new Ctx(); const osc = ctx.createOscillator(); const gain = ctx.createGain();
    osc.frequency.value = freq; gain.gain.value = 0.045; osc.connect(gain); gain.connect(ctx.destination); osc.start();
    setTimeout(() => { try { osc.stop(); } catch {} ctx.close().catch(()=>{}); }, duration);
  } catch {}
}
function beepSuccess() { beep(880,80); setTimeout(()=>beep(1180,90),90); }

function barcodeFormatName(result) {
  try {
    const raw = result.getBarcodeFormat();
    return BarcodeFormat[raw] || String(raw);
  } catch { return 'UNKNOWN'; }
}
function formatAllowed(name) {
  const mode = settings?.barcodeFilter || 'shipping';
  if (mode === 'all') return true;
  if (mode === 'qr') return name === 'QR_CODE';
  return ['QR_CODE','CODE_128','CODE_39','EAN_13','EAN_8','ITF','DATA_MATRIX','PDF_417','UPC_A','UPC_E'].includes(name);
}
function processDetectedResult(result, source='camera') {
  if (!result) return;
  const code = cleanCode(result.getText?.());
  if (!code) return;
  const format = barcodeFormatName(result);
  if (!formatAllowed(format)) return;
  const now = Date.now();
  const needed = Math.max(1, Number(settings?.scanConfirmations || 2));
  if (scanCandidate.code === code && scanCandidate.format === format && now - scanCandidate.at < 1200) scanCandidate.count++;
  else scanCandidate = { code, format, count:1, at:now };
  scanCandidate.at = now;
  if (scanCandidate.count >= needed) {
    scanCandidate = { code:null, format:null, count:0, at:0 };
    handleScan(code, source).catch(err => showToast(err.message || err));
  }
}

async function listCameras(preferred='') {
  let devices = [];
  try { devices = await BrowserCodeReader.listVideoInputDevices(); } catch (err) { console.warn('list cameras', err); }
  const old = preferred || els.cameraSelect.value || '';
  els.cameraSelect.innerHTML = '';
  if (!devices.length) {
    const opt = new Option('Default / Built-in Camera', ''); els.cameraSelect.add(opt); return [];
  }
  devices.forEach((d,i) => els.cameraSelect.add(new Option(d.label || `Camera ${i+1}`, d.deviceId)));
  if (old && devices.some(d => d.deviceId === old)) els.cameraSelect.value = old;
  return devices;
}
function stopLocalCamera() {
  try { cameraControls?.stop(); } catch {}
  cameraControls = null;
  if (cameraStream) { try { cameraStream.getTracks().forEach(t=>t.stop()); } catch {} }
  cameraStream = null;
  if (els.video.srcObject) { try { els.video.srcObject.getTracks().forEach(t=>t.stop()); } catch {}; els.video.srcObject = null; }
}
function stopPhoneMode() {
  clearInterval(phonePollTimer); clearInterval(phoneScanTimer); phonePollTimer = phoneScanTimer = null;
  ipcRenderer.invoke('network-camera:stop').catch(()=>{});
  els.phoneBridgePanel.classList.add('hidden');
  els.phoneFrame.style.display = 'none'; els.video.style.display = 'block';
}
async function applyAutofocus() {
  const track = cameraStream?.getVideoTracks?.()[0];
  if (!track) return;
  try {
    const caps = track.getCapabilities?.() || {};
    if (Array.isArray(caps.focusMode) && caps.focusMode.includes('continuous')) {
      await track.applyConstraints({ advanced:[{focusMode:'continuous'}] });
      els.cameraFocusStatus.textContent = 'Continuous autofocus enabled.';
    } else els.cameraFocusStatus.textContent = 'Autofocus is controlled by the camera/driver.';
  } catch { els.cameraFocusStatus.textContent = 'Autofocus is controlled by the camera/driver.'; }
}
async function startCamera(deviceId='') {
  if (cameraStarting) return;
  cameraStarting = true;
  currentCameraMode = 'local';
  stopPhoneMode(); stopLocalCamera();
  els.video.style.display = 'block'; els.phoneFrame.style.display = 'none';
  els.cameraMessage.textContent = 'Starting camera…'; els.cameraMessage.classList.remove('hidden');
  badge(els.cameraBadge, 'CAMERA STARTING', 'warning');
  try {
    cameraReader = new BrowserMultiFormatReader();
    cameraControls = await cameraReader.decodeFromVideoDevice(deviceId || undefined, els.video, (result) => {
      if (result) processDetectedResult(result, 'camera');
    });
    cameraStream = els.video.srcObject;
    if (!cameraStream?.getVideoTracks?.().length) throw new Error('Camera opened without a video stream.');
    await els.video.play();
    const track = cameraStream.getVideoTracks()[0];
    const activeId = track.getSettings?.().deviceId || deviceId || '';
    await listCameras(activeId);
    await applyAutofocus();
    els.cameraMessage.classList.add('hidden'); badge(els.cameraBadge, 'CAMERA LIVE', 'good');
    lastVideoTime = els.video.currentTime || 0; lastFrameAt = Date.now();
    showToast(`Camera ready: ${track.label || 'Default camera'}`);
    return true;
  } catch (err) {
    console.error('camera start', err); stopLocalCamera();
    const sys = await ipcRenderer.invoke('camera:system-status').catch(()=>null);
    let msg = err?.message || 'Camera failed to open.';
    if (sys?.cameraAccess === 'denied' || sys?.cameraAccess === 'restricted') msg = 'Windows camera access is blocked. Enable Camera access and desktop-app camera access in Windows Settings.';
    else if (['NotAllowedError','PermissionDeniedError'].includes(err?.name)) msg = 'Camera permission denied by Windows/Chromium.';
    else if (['NotReadableError','TrackStartError'].includes(err?.name)) msg = 'Camera is busy. Close Camera, Teams, Zoom, OBS, Discord, then Restart camera.';
    else if (['NotFoundError','DevicesNotFoundError'].includes(err?.name)) msg = 'No camera device was detected.';
    els.cameraMessage.textContent = `CAMERA ERROR — ${msg}`; els.cameraMessage.classList.remove('hidden');
    badge(els.cameraBadge, 'CAMERA ERROR', 'bad'); showToast(msg); return false;
  } finally { cameraStarting = false; }
}

async function pollPhoneFrame() {
  const r = await ipcRenderer.invoke('network-camera:get-frame');
  if (r?.bytes?.length) {
    const url = URL.createObjectURL(new Blob([r.bytes], {type:'image/jpeg'}));
    els.phoneFrame.onload = () => { if (phoneBlobUrl) URL.revokeObjectURL(phoneBlobUrl); phoneBlobUrl=url; els.cameraMessage.classList.add('hidden'); badge(els.cameraBadge,'PHONE LIVE','good'); lastFrameAt=Date.now(); };
    els.phoneFrame.src = url;
  } else if (r?.state === 'error') { badge(els.cameraBadge,'NETWORK CAMERA ERROR','bad'); els.cameraMessage.textContent=r.error||'Network camera error'; els.cameraMessage.classList.remove('hidden'); }
}
async function scanPhoneFrame() {
  if (phoneScanning || !els.phoneFrame.naturalWidth) return;
  phoneScanning = true;
  try {
    const c=els.scanCanvas, ctx=c.getContext('2d'); c.width=els.phoneFrame.naturalWidth; c.height=els.phoneFrame.naturalHeight;
    drawZoomed(ctx, els.phoneFrame, c.width, c.height, c.width, c.height, scannerZoom);
    const result = await canvasReader.decodeFromCanvas(c); if (result) processDetectedResult(result,'phone');
  } catch {} finally { phoneScanning=false; }
}
async function startPhoneMode() {
  stopLocalCamera(); currentCameraMode='phone'; els.video.style.display='none'; els.phoneFrame.style.display='block'; els.phoneBridgePanel.classList.remove('hidden');
  els.cameraMessage.textContent='Waiting for phone/network camera…'; els.cameraMessage.classList.remove('hidden'); badge(els.cameraBadge,'WAITING CAMERA','warning');
  const url=els.networkCameraUrl.value.trim(); if (url) await ipcRenderer.invoke('network-camera:start',url);
  await pollPhoneFrame(); phonePollTimer=setInterval(pollPhoneFrame,180); phoneScanTimer=setInterval(scanPhoneFrame,300);
}
async function startSelectedCamera() { return els.cameraMode.value === 'phone' ? startPhoneMode() : startCamera(els.cameraSelect.value || ''); }

function drawZoomed(ctx, source, sw, sh, dw, dh, zoom=1) {
  const z=Math.max(1,Number(zoom||1)); const cw=sw/z, ch=sh/z, sx=(sw-cw)/2, sy=(sh-ch)/2;
  ctx.drawImage(source,sx,sy,cw,ch,0,0,dw,dh);
}
function drawLoop() {
  const source = currentCameraMode==='phone' && els.phoneFrame.naturalWidth ? els.phoneFrame : (els.video.readyState>=2 ? els.video : null);
  const sw = source === els.phoneFrame ? els.phoneFrame.naturalWidth : els.video.videoWidth;
  const sh = source === els.phoneFrame ? els.phoneFrame.naturalHeight : els.video.videoHeight;
  if (source && sw && sh) {
    if (els.canvas.width!==sw || els.canvas.height!==sh) { els.canvas.width=sw; els.canvas.height=sh; }
    const ctx=els.canvas.getContext('2d'); drawZoomed(ctx,source,sw,sh,sw,sh,farViewZoom);
    if (currentSession) drawRecordingOverlay(ctx,sw,sh);
  } else {
    if (!els.canvas.width) { els.canvas.width=1280; els.canvas.height=720; }
    const ctx=els.canvas.getContext('2d'); ctx.fillStyle='#000'; ctx.fillRect(0,0,els.canvas.width,els.canvas.height);
  }
  animationId=requestAnimationFrame(drawLoop);
}
function drawRecordingOverlay(ctx,w,h) {
  const code=currentSession?.code||''; const now=new Date().toLocaleString();
  const boxH=Math.max(100,Math.round(h*.17)); ctx.fillStyle='rgba(0,0,0,.72)'; ctx.fillRect(0,h-boxH,w,boxH);
  ctx.fillStyle='#ff3038'; ctx.font=`700 ${Math.max(18,Math.round(w*.018))}px system-ui`; ctx.fillText('● REC',24,h-boxH+34);
  ctx.fillStyle='#fff'; ctx.font=`800 ${Math.max(24,Math.round(w*.027))}px system-ui`; ctx.fillText(code,24,h-boxH+72);
  ctx.fillStyle='#d8d8dc'; ctx.font=`600 ${Math.max(13,Math.round(w*.012))}px system-ui`; ctx.fillText(`${settings?.stationName||'Station 01'} • ${now}`,24,h-18);
}
function preferredMime() { return ['video/webm;codecs=vp9','video/webm;codecs=vp8','video/webm'].find(t=>MediaRecorder.isTypeSupported(t))||''; }
function startSession(code) {
  if (!els.canvas.captureStream) throw new Error('Video recording is not supported on this PC.');
  const stream=els.canvas.captureStream(30), mime=preferredMime();
  const recorder=new MediaRecorder(stream,mime?{mimeType:mime,videoBitsPerSecond:4500000}:undefined);
  const s={code,recorder,chunks:[],startedAt:Date.now(),exception:null,details:null,recoveryPath:null,stopping:false};
  ipcRenderer.invoke('recovery:start',{code,sessionId:`${Date.now()}-${Math.random().toString(16).slice(2)}`}).then(r=>{if(r?.ok)s.recoveryPath=r.filePath;}).catch(()=>{});
  recorder.ondataavailable=e=>{ if(!e.data?.size)return; s.chunks.push(e.data); if(s.recoveryPath)e.data.arrayBuffer().then(b=>ipcRenderer.invoke('recovery:append',{filePath:s.recoveryPath,buffer:b})).catch(()=>{}); };
  recorder.start(500); return s;
}
async function stopAndSaveSession(s) {
  if (!s || s.stopping) return null; s.stopping=true;
  return new Promise(resolve=>{
    const finish=async()=>{
      try {
        const endedAt=Date.now(); const blob=new Blob(s.chunks,{type:s.recorder.mimeType||'video/webm'}); const buffer=await blob.arrayBuffer();
        const r=await ipcRenderer.invoke('recording:save',{code:s.code,startedAt:s.startedAt,endedAt,buffer,exception:s.exception,details:s.details});
        if(r?.ok){ if(s.recoveryPath)await ipcRenderer.invoke('recovery:finish',{filePath:s.recoveryPath}).catch(()=>{}); addHistory(r,s); }
        resolve(r);
      } catch(err){ console.error(err); showToast(`Save failed: ${err.message||err}`); resolve(null); }
    };
    if(s.recorder.state==='inactive') finish(); else { s.recorder.addEventListener('stop',finish,{once:true}); try{s.recorder.requestData();}catch{} s.recorder.stop(); }
  });
}
function updateRecordingUi() {
  if(currentSession?.recorder?.state==='paused'){badge(els.recordBadge,'PAUSED','warning');els.recordingOverlay.classList.remove('show');els.recDot.classList.remove('live');els.transportStatus.textContent=`Paused • ${currentSession.code}`;}
  else if(currentSession?.recorder && currentSession.recorder.state!=='inactive'){badge(els.recordBadge,'● RECORDING','bad');els.recordingOverlay.classList.add('show');els.recDot.classList.add('live');els.transportStatus.textContent=`Recording • ${currentSession.code}`;}
  else{badge(els.recordBadge,'NOT RECORDING','neutral');els.recordingOverlay.classList.remove('show');els.recDot.classList.remove('live');els.transportStatus.textContent='Waiting for scan';}
}
function setDetails(d) {
  activeDetails=d; els.detailTracking.textContent=d?.tracking||'—'; els.detailOrder.textContent=d?.order||'—'; els.detailCourier.textContent=d?.courier||'—'; els.detailCustomer.textContent=d?.customer||'—'; els.detailItem.textContent=d?.item||'—'; els.detailQty.textContent=d?.qty??'—'; els.detailStatus.textContent=d?.status||'—';
}
async function saveWaybillSnapshot(code) {
  try {
    const source=currentCameraMode==='phone'?els.phoneFrame:els.video; const sw=source===els.phoneFrame?source.naturalWidth:source.videoWidth; const sh=source===els.phoneFrame?source.naturalHeight:source.videoHeight;
    if(!sw||!sh)return null; const c=document.createElement('canvas'); c.width=1280; c.height=720; drawZoomed(c.getContext('2d'),source,sw,sh,c.width,c.height,scannerZoom);
    const blob=await new Promise(r=>c.toBlob(r,'image/png')); if(!blob)return null; return ipcRenderer.invoke('snapshot:save',{code,capturedAt:Date.now(),buffer:await blob.arrayBuffer()});
  } catch(err){console.warn('snapshot',err);return null;}
}
async function handleScan(rawCode, source='camera') {
  const code=cleanCode(rawCode); if(code.length<3||scanBusy)return null;
  const now=Date.now(); if(currentSession?.code===code)return null; if(lastAccepted.code===code&&now-lastAccepted.at<SCAN_DEBOUNCE_MS)return null;
  scanBusy=true; lastAccepted={code,at:now}; const previous=currentSession;
  try {
    els.currentCode.textContent=code; setDetails({tracking:code,status:'Recording'}); badge(els.lookupState,'ACTIVE','good');
    const next=startSession(code); next.details=activeDetails; currentSession=next; updateRecordingUi();
    if(settings?.successSoundEnabled!==false)beepSuccess();
    await saveWaybillSnapshot(code);
    if(settings?.bigSellerAutoSubmit!==false){ipcRenderer.invoke('bigseller:submit',code).then(r=>{els.bigSellerStatus.textContent=r?.ok?`Submitted ${code} to BigSeller.`:(r?.skipped?'BigSeller URL not configured.':(r?.error||'BigSeller bridge unavailable.'));}).catch(()=>{});}
    if(previous)setTimeout(()=>stopAndSaveSession(previous),Math.max(0,Number(settings?.overlapMs||900)));
    return next;
  } finally { scanBusy=false; }
}
async function startOrResumeRecording(){if(currentSession?.recorder?.state==='paused'){currentSession.recorder.resume();updateRecordingUi();return;}if(currentSession?.recorder?.state==='recording'){showToast('Recording already active.');return;}const code=cleanCode(els.manualCode.value)||`MANUAL-${Date.now()}`;await handleScan(code,'manual');}
async function pauseRecording(){if(!currentSession)return showToast('No active recording.');if(currentSession.recorder.state==='recording')currentSession.recorder.pause();else if(currentSession.recorder.state==='paused')currentSession.recorder.resume();updateRecordingUi();}
async function stopCurrentRecording(){if(!currentSession)return null;const s=currentSession;currentSession=null;setDetails(null);els.currentCode.textContent='Waiting for scan';badge(els.lookupState,'IDLE','neutral');updateRecordingUi();return stopAndSaveSession(s);}
function addHistory(r,s){const empty=els.historyBody.querySelector('.empty-row');if(empty)empty.remove();const tr=document.createElement('tr');tr.innerHTML=`<td>${new Date(r.startedAt).toLocaleTimeString()}</td><td><strong>${escapeHtml(r.code)}</strong></td><td>${formatDuration(new Date(r.endedAt)-new Date(r.startedAt))}</td><td><button class="file-button">${escapeHtml(r.filename)}</button></td><td class="storage-status">Local</td>`;tr.querySelector('button').onclick=()=>ipcRenderer.invoke('file:show',r.path);els.historyBody.prepend(tr);historyFiles.set(r.path,{button:tr.querySelector('button'),statusCell:tr.querySelector('.storage-status')});els.scanCount.textContent=`${++savedCount} saved`;}

function evaluateQuality(){if(settings?.cameraQualityEnabled===false)return badge(els.qualityBadge,'QUALITY OFF','neutral');const source=currentCameraMode==='phone'?els.phoneFrame:els.video;const sw=source===els.phoneFrame?source.naturalWidth:source.videoWidth,sh=source===els.phoneFrame?source.naturalHeight:source.videoHeight;if(!sw||!sh)return badge(els.qualityBadge,'QUALITY —','neutral');const c=document.createElement('canvas');c.width=160;c.height=90;const ctx=c.getContext('2d',{willReadFrequently:true});ctx.drawImage(source,0,0,c.width,c.height);const d=ctx.getImageData(0,0,c.width,c.height).data;let sum=0;for(let i=0;i<d.length;i+=4)sum+=(d[i]*.299+d[i+1]*.587+d[i+2]*.114);const lum=sum/(d.length/4);if(lum<38)badge(els.qualityBadge,'TOO DARK','bad');else if(lum>230)badge(els.qualityBadge,'TOO BRIGHT','warning');else badge(els.qualityBadge,'QUALITY GOOD','good');}
function updateTimer(){els.timer.textContent=currentSession?formatDuration(Date.now()-currentSession.startedAt):'00:00';}
function updateZooms(){farViewZoom=clamp(els.farViewZoom.value||settings?.farViewZoom||1,1,1.75);scannerZoom=clamp(els.scannerZoom.value||settings?.scannerZoom||1.75,1,3);els.farViewZoomValue.textContent=`${farViewZoom.toFixed(2)}×`;els.scannerZoomValue.textContent=`${scannerZoom.toFixed(2)}×`;els.video.style.transform=`scale(${farViewZoom})`;els.phoneFrame.style.transform=`scale(${farViewZoom})`;}

function renderSettings(){els.stationName.value=settings.stationName||'Station 01';els.operatorName.value=settings.operatorName||'';els.overlapMs.value=String(settings.overlapMs||900);els.folderPath.textContent=settings.recordingFolder||'—';els.serverFolder.value=settings.serverFolder||'';els.autoSyncEnabled.checked=settings.autoSyncEnabled!==false;els.successSoundEnabled.checked=settings.successSoundEnabled!==false;els.networkCameraUrl.value=settings.networkCameraUrl||'';els.autoStartWithWindows.checked=settings.autoStartWithWindows!==false;els.cameraQualityEnabled.checked=settings.cameraQualityEnabled!==false;els.scanConfirmations.value=String(settings.scanConfirmations||2);els.barcodeFilter.value=settings.barcodeFilter||'shipping';els.bigSellerAutoSubmit.checked=settings.bigSellerAutoSubmit!==false;els.bigSellerUrl.value=settings.bigSellerUrl||'';els.farViewZoom.value=String(settings.farViewZoom||1);els.scannerZoom.value=String(settings.scannerZoom||1.75);updateZooms();const d=new Date(),ds=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;els.todayFolder.textContent=`Today: ${settings.recordingFolder}\\${ds}`;}
async function saveSettings(){settings=await ipcRenderer.invoke('settings:update',{stationName:els.stationName.value.trim()||'Station 01',operatorName:els.operatorName.value.trim(),overlapMs:Number(els.overlapMs.value||900),serverFolder:els.serverFolder.value.trim(),autoSyncEnabled:els.autoSyncEnabled.checked,successSoundEnabled:els.successSoundEnabled.checked,cameraMode:els.cameraMode.value||'local',networkCameraUrl:els.networkCameraUrl.value.trim(),farViewZoom:Number(els.farViewZoom.value||1),scannerZoom:Number(els.scannerZoom.value||1.75),autoStartWithWindows:els.autoStartWithWindows.checked,cameraQualityEnabled:els.cameraQualityEnabled.checked,scanConfirmations:Number(els.scanConfirmations.value||2),barcodeFilter:els.barcodeFilter.value||'shipping',bigSellerAutoSubmit:els.bigSellerAutoSubmit.checked,bigSellerUrl:els.bigSellerUrl.value.trim()});renderSettings();}
function renderSyncStatus(s={}){const state=s.state||'not-configured',message=s.message||'SERVER NOT SET';badge(els.syncBadge,message,state==='online'?'good':state==='syncing'?'warning':state==='offline'?'bad':'neutral');els.syncStatusText.textContent=state==='online'?'Server online. Verified files are removed locally after transfer.':state==='offline'?'Server offline. Evidence remains safely on this PC.':state==='disabled'?'Auto Sync is off.':'Set a server shared folder to enable transfer.';for(const moved of(s.transferred||[])){const row=historyFiles.get(moved.localFile);if(row){row.button.onclick=()=>ipcRenderer.invoke('file:show',moved.serverFile);row.statusCell.textContent='Server';}}}

async function runServerSearch(){const q=cleanCode(els.serverSearchInput.value);if(!q)return;els.serverSearchResults.textContent='Searching…';const r=await ipcRenderer.invoke('evidence:search',q);if(!r?.ok){els.serverSearchResults.textContent=r?.error||'Search failed.';return;}if(!r.results?.length){els.serverSearchResults.textContent='No matching evidence found.';return;}els.serverSearchResults.innerHTML='';for(const item of r.results){const row=document.createElement('div');row.className='search-result-item';row.innerHTML=`<div><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.day||'')}</small></div><div class="search-result-actions"><button class="btn secondary open">Open</button>${['.webm','.mp4'].includes(item.ext)?'<button class="btn primary play">Play</button>':''}${item.ext==='.png'?'<button class="btn primary view">View</button>':''}</div>`;row.querySelector('.open').onclick=()=>ipcRenderer.invoke('file:show',item.path);row.querySelector('.play')?.addEventListener('click',()=>{els.serverVideoPlayer.src=item.url;els.serverVideoPlayer.style.display='block';els.serverVideoPlayer.play().catch(()=>{});});row.querySelector('.view')?.addEventListener('click',()=>{els.serverWaybillPreview.src=item.url;els.serverWaybillPreview.style.display='block';});els.serverSearchResults.appendChild(row);}}

async function runSmokeTest(){const enabled=await ipcRenderer.invoke('smoke:is-enabled');if(!enabled)return;try{if(!cameraStream?.getVideoTracks?.().length)throw new Error('Fake camera did not become live.');await sleep(700);await handleScan('SMOKE-TEST-001','smoke');await sleep(1300);const saved=await stopCurrentRecording();if(!saved?.ok)throw new Error('Recording save failed in smoke test.');await ipcRenderer.invoke('smoke:pass',{camera:true,recording:true,file:saved.filename});}catch(err){await ipcRenderer.invoke('smoke:fail',err?.stack||err?.message||String(err));}}

function wireEvents(){
  els.restartCameraBtn.onclick=()=>startSelectedCamera(); els.diagnoseCameraBtn.onclick=async()=>{const sys=await ipcRenderer.invoke('camera:system-status');let cams=[];try{cams=await BrowserCodeReader.listVideoInputDevices();}catch{}const msg=`Windows access: ${sys?.cameraAccess||'unknown'} | Cameras: ${cams.length} ${cams.map(x=>x.label||'Camera').join(', ')} | Electron ${sys?.electron||'?'}`;els.cameraMessage.textContent=msg;els.cameraMessage.classList.remove('hidden');showToast(msg);};
  els.cameraSelect.onchange=()=>{if(els.cameraMode.value==='local')startCamera(els.cameraSelect.value);}; els.cameraMode.onchange=async()=>{await saveSettings();await startSelectedCamera();};
  els.connectNetworkCameraBtn.onclick=async()=>{const url=els.networkCameraUrl.value.trim();if(!url)return showToast('Enter a network camera URL.');els.cameraMode.value='phone';await saveSettings();await startPhoneMode();};
  els.manualScanBtn.onclick=()=>{const c=cleanCode(els.manualCode.value);if(c){handleScan(c,'manual');els.manualCode.value='';}}; els.manualCode.onkeydown=e=>{if(e.key==='Enter')els.manualScanBtn.click();};
  els.startVideoBtn.onclick=startOrResumeRecording; els.pauseVideoBtn.onclick=pauseRecording; els.stopVideoBtn.onclick=stopCurrentRecording;
  els.testSoundBtn.onclick=beepSuccess; els.openFolderBtn.onclick=()=>ipcRenderer.invoke('folder:open-recordings');
  els.chooseServerFolderBtn.onclick=async()=>{settings=await ipcRenderer.invoke('settings:choose-server-folder');renderSettings();renderSyncStatus(await ipcRenderer.invoke('sync:now'));};
  els.syncNowBtn.onclick=async()=>{renderSyncStatus({state:'syncing',message:'SYNCING…'});renderSyncStatus(await ipcRenderer.invoke('sync:now'));};
  els.openServerBtn.onclick=async()=>{const r=await ipcRenderer.invoke('folder:open-server');if(!r?.ok)showToast(r?.error||'Server unavailable.');};
  els.openBigSellerBtn.onclick=async()=>{await saveSettings();if(!els.bigSellerUrl.value.trim())return showToast('Set BigSeller URL first.');const r=await ipcRenderer.invoke('bigseller:open');els.bigSellerStatus.textContent=r?.ok?'BigSeller bridge opened.':(r?.error||'BigSeller bridge failed.');};
  els.markExceptionBtn.onclick=()=>{if(!currentSession)return showToast('Scan a parcel first.');currentSession.exception=els.exceptionType.value||null;els.exceptionStatus.textContent=currentSession.exception?`Exception: ${currentSession.exception}`:'No exception on current parcel.';};
  els.endShiftBtn.onclick=async()=>{const r=await ipcRenderer.invoke('shift:verify');els.shiftStatus.textContent=r?.ok?'✓ Shift clear.':`Needs attention — server ${r?.serverOnline?'online':'offline'}, pending videos ${r?.pendingVideos??0}, evidence ${r?.pendingEvidenceFiles??0}, recovery ${r?.recoveryFiles??0}`;};
  els.serverSearchBtn.onclick=runServerSearch;els.serverSearchInput.onkeydown=e=>{if(e.key==='Enter')runServerSearch();};
  for(const el of [els.stationName,els.operatorName,els.overlapMs,els.serverFolder,els.autoSyncEnabled,els.successSoundEnabled,els.autoStartWithWindows,els.cameraQualityEnabled,els.scanConfirmations,els.barcodeFilter,els.bigSellerAutoSubmit,els.bigSellerUrl])el.addEventListener('change',saveSettings);
  els.farViewZoom.oninput=updateZooms;els.farViewZoom.onchange=saveSettings;els.scannerZoom.oninput=updateZooms;els.scannerZoom.onchange=saveSettings;
  window.addEventListener('keydown',e=>{if(e.repeat)return;if(e.key==='F1'){e.preventDefault();startOrResumeRecording();}if(e.key==='F2'){e.preventDefault();pauseRecording();}if(e.key==='F3'){e.preventDefault();stopCurrentRecording();}});
}

ipcRenderer.on('sync:status',(e,s)=>renderSyncStatus(s));
ipcRenderer.on('recovery:status',(e,s)=>{if(s?.recovered?.length)showToast(`${s.recovered.length} interrupted recording(s) recovered.`);});
ipcRenderer.on('watchdog:tick',async()=>{if(cameraStarting||watchdogRestarting||currentCameraMode!=='local'||!cameraStream)return;if(els.video.readyState>=2){const t=els.video.currentTime;if(Math.abs(t-lastVideoTime)>.02){lastVideoTime=t;lastFrameAt=Date.now();return;}}if(Date.now()-lastFrameAt<15000)return;watchdogRestarting=true;badge(els.cameraBadge,'CAMERA FROZEN','bad');try{await startCamera(els.cameraSelect.value||'');}finally{watchdogRestarting=false;lastFrameAt=Date.now();}});

async function init(){
  settings=await ipcRenderer.invoke('settings:get'); renderSettings(); wireEvents(); drawLoop(); timerId=setInterval(updateTimer,250); qualityTimer=setInterval(evaluateQuality,1400);
  els.cameraMode.value='local'; settings=await ipcRenderer.invoke('settings:update',{cameraMode:'local'});
  await listCameras(); const ok=await startCamera(els.cameraSelect.value||'');
  renderSyncStatus(await ipcRenderer.invoke('sync:now'));
  if(ok)await runSmokeTest(); else if(await ipcRenderer.invoke('smoke:is-enabled'))await ipcRenderer.invoke('smoke:fail','Camera failed to become live.');
}

window.addEventListener('beforeunload',()=>{stopLocalCamera();stopPhoneMode();cancelAnimationFrame(animationId);clearInterval(timerId);clearInterval(qualityTimer);if(phoneBlobUrl)URL.revokeObjectURL(phoneBlobUrl);});
window.addEventListener('error',e=>{console.error(e.error||e.message);showToast(`Runtime error: ${e.message}`);});
window.addEventListener('unhandledrejection',e=>{console.error(e.reason);showToast(`Runtime error: ${e.reason?.message||e.reason}`);});

init().catch(async err=>{console.error(err);showToast(`Startup failed: ${err?.message||err}`);if(await ipcRenderer.invoke('smoke:is-enabled').catch(()=>false))await ipcRenderer.invoke('smoke:fail',err?.stack||err?.message||String(err));});
'''
(ROOT / 'src' / 'renderer.js').write_text(renderer, encoding='utf-8')

# ---------------- index version ----------------
index_path = ROOT / 'src' / 'index.html'
html = index_path.read_text(encoding='utf-8')
html = re.sub(r'<span class="version-tag">v[^<]+</span>', '<span class="version-tag">v3.0.0</span>', html, count=1)
index_path.write_text(html, encoding='utf-8')

# ---------------- package pinning ----------------
pkg_path = ROOT / 'package.json'
pkg = json.loads(pkg_path.read_text(encoding='utf-8'))
pkg['version'] = '3.0.0'
pkg['description'] = 'ScanCode v3 stable runtime rebuild with pinned Electron/ZXing versions, runtime webcam smoke testing, parcel recording, evidence capture, server sync and BigSeller bridge.'
pkg['dependencies'] = {'@zxing/browser':'0.2.1','@zxing/library':'0.22.0'}
pkg['devDependencies'] = {'electron':'43.4.0','electron-builder':'26.15.3'}
pkg.setdefault('scripts', {})['start'] = 'electron .'
pkg['scripts']['smoke'] = 'electron . --smoke-test'
pkg['scripts']['dist'] = 'electron-builder --win nsis portable --publish never'
pkg['scripts']['dist:setup'] = 'electron-builder --win nsis --publish never'
pkg_path.write_text(json.dumps(pkg, indent=2) + '\n', encoding='utf-8')

# ---------------- QA rewrite ----------------
qa = r'''const fs=require('fs'),path=require('path'),cp=require('child_process');
const root=path.resolve(__dirname,'..');const read=p=>fs.readFileSync(path.join(root,p),'utf8');
const html=read('src/index.html'),renderer=read('src/renderer.js'),main=read('main.js'),pkg=JSON.parse(read('package.json'));
let pass=0,fail=0;function check(n,c){console.log(`${c?'PASS':'FAIL'}  ${n}`);c?pass++:fail++;}
for(const f of ['main.js','src/renderer.js']){const r=cp.spawnSync(process.execPath,['--check',path.join(root,f)],{encoding:'utf8'});check(`Syntax ${f}`,r.status===0);}
const ids=[...html.matchAll(/id="([^"]+)"/g)].map(x=>x[1]);const refs=[...renderer.matchAll(/\$\('([^']+)'\)/g)].map(x=>x[1]);check('All renderer UI refs exist',refs.every(x=>ids.includes(x)));
const invokes=[...renderer.matchAll(/ipcRenderer\.invoke\(['"]([^'"]+)/g)].map(x=>x[1]);const handlers=[...main.matchAll(/ipcMain\.handle\(['"]([^'"]+)/g)].map(x=>x[1]);check('All renderer IPC calls have handlers',invokes.every(x=>handlers.includes(x)));
check('Pinned Electron',pkg.devDependencies?.electron==='43.4.0');check('Pinned ZXing browser',pkg.dependencies?.['@zxing/browser']==='0.2.1');check('Pinned ZXing library',pkg.dependencies?.['@zxing/library']==='0.22.0');
check('Direct webcam pipeline',renderer.includes('decodeFromVideoDevice'));check('Runtime smoke mode',main.includes("--smoke-test")&&renderer.includes('runSmokeTest'));check('Smoke camera + recording',renderer.includes('SMOKE-TEST-001')&&renderer.includes("smoke:pass"));
check('Recording controls',renderer.includes('startVideoBtn')&&renderer.includes('pauseVideoBtn')&&renderer.includes('stopVideoBtn'));check('Evidence screenshot',renderer.includes('saveWaybillSnapshot'));check('Server sync UI',renderer.includes('sync:now'));check('BigSeller bridge',renderer.includes('bigseller:submit'));check('Server search',renderer.includes('evidence:search'));check('End shift',renderer.includes('shift:verify'));
console.log(`PASS ${pass} / FAIL ${fail}`);process.exit(fail?1:0);
'''
(ROOT/'qa'/'qa.js').write_text(qa, encoding='utf-8')

print('ScanCode v3.0.0 stable runtime rebuild applied.')

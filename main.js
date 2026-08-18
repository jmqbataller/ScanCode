const { app, BrowserWindow, ipcMain, dialog, shell, session, systemPreferences, protocol, net } = require('electron');
const path = require('path');
const fs = require('fs');
const http = require('http');
const https = require('https');
const os = require('os');
const crypto = require('crypto');
const { pathToFileURL } = require('url');

const SMOKE_TEST = process.argv.includes('--smoke-test');
if (SMOKE_TEST) {
  app.commandLine.appendSwitch('use-fake-device-for-media-stream');
  app.commandLine.appendSwitch('use-fake-ui-for-media-stream');
  app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');
}


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

let mainWindow;
let syncTimer = null;
let syncRunning = false;
let dailyFolderTimer = null;
let networkCameraRequest = null;
let networkCameraRetry = null;
let latestNetworkFrame = null;
let latestNetworkFrameAt = 0;
let networkCameraUrl = '';
let networkCameraState = 'idle';
let networkCameraError = '';
let bigSellerWindow = null;
let watchdogTimer = null;

function settingsPath() {
  return path.join(app.getPath('userData'), 'settings.json');
}

function localRecordingRoot() {
  return path.join(app.getPath('documents'), 'ScanCode');
}

function defaultSettings() {
  return {
    recordingFolder: localRecordingRoot(),
    stationName: 'Station 01',
    operatorName: '',
    overlapMs: 900,
    serverFolder: '',
    autoSyncEnabled: true,
    syncIntervalSeconds: 20,
    successSoundEnabled: true,
    cameraMode: 'local',
    networkCameraUrl: '',
    farViewZoom: 1.0,
    scannerZoom: 1.75,
    autoStartWithWindows: true,
    barcodeFilter: 'shipping',
    scanConfirmations: 2,
    cameraQualityEnabled: true,
    bigSellerAutoSubmit: true,
    bigSellerUrl: ''
  };
}

function readSettings() {
  try {
    const p = settingsPath();
    if (!fs.existsSync(p)) return defaultSettings();
    const saved = JSON.parse(fs.readFileSync(p, 'utf8'));
    return {
      ...defaultSettings(),
      ...saved,
      // Local storage is intentionally fixed to Documents\\ScanCode.
      recordingFolder: localRecordingRoot()
    };
  } catch {
    return defaultSettings();
  }
}

function writeSettings(next) {
  const merged = {
    ...readSettings(),
    ...next,
    recordingFolder: localRecordingRoot()
  };
  fs.mkdirSync(path.dirname(settingsPath()), { recursive: true });
  fs.writeFileSync(settingsPath(), JSON.stringify(merged, null, 2));
  restartSyncTimer();
  try {
    app.setLoginItemSettings({
      openAtLogin: Boolean(merged.autoStartWithWindows),
      path: process.execPath
    });
  } catch {}
  return merged;
}

function safeName(value) {
  return String(value || 'UNKNOWN')
    .trim()
    .replace(/[<>:"/\\|?*\x00-\x1F]/g, '_')
    .replace(/\s+/g, '_')
    .slice(0, 100);
}

function dateFolder(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function timeStamp(date) {
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  const ss = String(date.getSeconds()).padStart(2, '0');
  return `${hh}-${mm}-${ss}`;
}

function imageFilenameBase(code) {
  return `${safeName(code)}_waybill`;
}

function metadataFilename(code) {
  return `${safeName(code)}.json`;
}

function partialRoot() {
  return path.join(localRecordingRoot(), '.recovery');
}


async function sha256File(filePath) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256');
    const stream = fs.createReadStream(filePath);
    stream.on('error', reject);
    stream.on('data', chunk => hash.update(chunk));
    stream.on('end', () => resolve(hash.digest('hex')));
  });
}

async function cleanupEmptyLocalDayFolders(localRoot) {
  let entries = [];
  try { entries = await fs.promises.readdir(localRoot, { withFileTypes: true }); } catch { return; }
  const today = dateFolder(new Date());
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name === today || entry.name.startsWith('.')) continue;
    const full = path.join(localRoot, entry.name);
    try {
      const contents = await fs.promises.readdir(full);
      if (!contents.length) await fs.promises.rmdir(full);
    } catch {}
  }
  ensureDailyLocalFolder();
}


function ensureDailyLocalFolder(date = new Date()) {
  const folder = path.join(localRecordingRoot(), dateFolder(date));
  fs.mkdirSync(folder, { recursive: true });
  return folder;
}

async function ensureDailyServerFolder(date = new Date()) {
  const settings = readSettings();
  const serverRoot = String(settings.serverFolder || '').trim();
  if (!serverRoot || !(await pathAccessible(serverRoot))) return null;
  const folder = path.join(serverRoot, dateFolder(date));
  await fs.promises.mkdir(folder, { recursive: true });
  return folder;
}

function startDailyFolderTimer() {
  if (dailyFolderTimer) clearInterval(dailyFolderTimer);
  ensureDailyLocalFolder();
  ensureDailyServerFolder().catch(() => {});
  dailyFolderTimer = setInterval(() => {
    ensureDailyLocalFolder();
    ensureDailyServerFolder().catch(() => {});
  }, 60 * 1000);
}

async function listEvidenceFiles(root) {
  const found = [];
  if (!fs.existsSync(root)) return found;

  const walk = async (dir) => {
    let entries;
    try { entries = await fs.promises.readdir(dir, { withFileTypes: true }); }
    catch { return; }

    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === '.recovery') continue;
        await walk(full);
      } else if (entry.isFile() && /\.(webm|mp4|png|json)$/i.test(entry.name)) {
        found.push(full);
      }
    }
  };

  await walk(root);
  return found;
}

function evidenceDayFromPath(localFile, localRoot) {
  const rel = path.relative(localRoot, localFile);
  const first = rel.split(path.sep)[0];
  return /^\d{4}-\d{2}-\d{2}$/.test(first) ? first : dateFolder(new Date());
}

function isVideoFile(filePath) {
  return /\.(webm|mp4)$/i.test(filePath);
}

async function uniqueDestination(destPath) {
  try {
    await fs.promises.access(destPath);
  } catch {
    return destPath;
  }

  const parsed = path.parse(destPath);
  let i = 2;
  while (true) {
    const candidate = path.join(parsed.dir, `${parsed.name}_${i}${parsed.ext}`);
    try {
      await fs.promises.access(candidate);
      i += 1;
    } catch {
      return candidate;
    }
  }
}

async function transferOneFile(localFile, localRoot, serverRoot) {
  // Transfer evidence FILES only, not the scanner PC folder itself.
  // The server receives a flat daily set: video + waybill image + metadata JSON.
  const day = evidenceDayFromPath(localFile, localRoot);
  const serverDayFolder = path.join(serverRoot, day);
  await fs.promises.mkdir(serverDayFolder, { recursive: true });

  const target = await uniqueDestination(path.join(serverDayFolder, path.basename(localFile)));
  const temp = `${target}.scancode-partial-${safeName(os.hostname())}-${crypto.randomBytes(4).toString('hex')}`;

  const srcStat = await fs.promises.stat(localFile);
  const srcHashPromise = sha256File(localFile);
  await fs.promises.copyFile(localFile, temp);

  const tempStat = await fs.promises.stat(temp);
  if (srcStat.size !== tempStat.size) {
    await fs.promises.unlink(temp).catch(() => {});
    throw new Error('Server copy size verification failed. Local video was kept.');
  }

  const [srcHash, tempHash] = await Promise.all([srcHashPromise, sha256File(temp)]);
  if (srcHash !== tempHash) {
    await fs.promises.unlink(temp).catch(() => {});
    throw new Error('Server copy checksum verification failed. Local video was kept.');
  }

  // Rename the verified temporary file to its final filename on the server.
  await fs.promises.rename(temp, target);

  const finalStat = await fs.promises.stat(target);
  if (finalStat.size !== srcStat.size) {
    throw new Error('Server final-file verification failed. Local video was kept.');
  }

  // Critical rule: local scanner evidence is deleted ONLY after the server copy is verified.
  await fs.promises.unlink(localFile);

  return {
    localFile,
    serverFile: target,
    bytes: srcStat.size,
    sha256: srcHash,
    station: readSettings().stationName || 'Station 01',
    pc: os.hostname()
  };
}

async function syncPendingVideos(reason = 'timer') {
  if (syncRunning) return { state: 'syncing', message: 'SYNC IN PROGRESS…', ok: false, busy: true };
  syncRunning = true;

  try {
    const settings = readSettings();
    const localRoot = settings.recordingFolder;
    const serverRoot = String(settings.serverFolder || '').trim();

    if (!settings.autoSyncEnabled) {
      const status = { state: 'disabled', message: 'AUTO SYNC OFF', moved: 0, reason };
      emitSyncStatus(status);
      return status;
    }

    if (!serverRoot) {
      const status = { state: 'not-configured', message: 'SERVER NOT SET', moved: 0, reason };
      emitSyncStatus(status);
      return status;
    }

    const reachable = await pathAccessible(serverRoot);
    if (!reachable) {
      const pending = (await listEvidenceFiles(localRoot)).filter(isVideoFile).length;
      const status = {
        state: 'offline',
        message: pending ? `SERVER OFFLINE • ${pending} PENDING` : 'SERVER OFFLINE',
        pending,
        moved: 0,
        reason
      };
      emitSyncStatus(status);
      return status;
    }

    const files = await listEvidenceFiles(localRoot);
    if (!files.length) {
      const status = { state: 'online', message: 'SERVER ONLINE • SYNCED', pending: 0, moved: 0, reason };
      emitSyncStatus(status);
      return status;
    }

    const videoPending = files.filter(isVideoFile).length;
    emitSyncStatus({ state: 'syncing', message: `SYNCING ${videoPending} PARCEL${videoPending === 1 ? '' : 'S'}…`, pending: videoPending, moved: 0, reason });

    let moved = 0;
    let failed = 0;
    const transferred = [];

    for (const file of files) {
      try {
        const result = await transferOneFile(file, localRoot, serverRoot);
        transferred.push(result);
        moved += 1;
      } catch (err) {
        console.error('ScanCode sync failed:', file, err);
        failed += 1;
        // If the server disappears mid-sync, stop and retry on the next cycle.
        if (!(await pathAccessible(serverRoot))) break;
      }
    }

    await cleanupEmptyLocalDayFolders(localRoot);
    const remaining = (await listEvidenceFiles(localRoot)).filter(isVideoFile).length;
    const state = failed || remaining ? 'warning' : 'online';
    const message = remaining
      ? `SERVER ONLINE • ${remaining} PENDING`
      : `SERVER ONLINE • ${moved ? `${moved} MOVED` : 'SYNCED'}`;

    const status = { state, message, pending: remaining, moved, failed, transferred, reason };
    emitSyncStatus(status);
    return status;
  } finally {
    syncRunning = false;
  }
}

function restartSyncTimer() {
  if (syncTimer) clearInterval(syncTimer);
  const seconds = Math.max(10, Number(readSettings().syncIntervalSeconds || 20));
  syncTimer = setInterval(() => syncPendingVideos('timer'), seconds * 1000);
}


function stopNetworkCamera() {
  if (networkCameraRetry) clearTimeout(networkCameraRetry);
  networkCameraRetry = null;
  if (networkCameraRequest) {
    try { networkCameraRequest.destroy(); } catch {}
  }
  networkCameraRequest = null;
  networkCameraState = 'idle';
}

function connectNetworkCamera(url) {
  stopNetworkCamera();
  networkCameraUrl = String(url || '').trim();
  latestNetworkFrame = null;
  latestNetworkFrameAt = 0;
  networkCameraError = '';
  if (!networkCameraUrl) return;

  const run = () => {
    let parsed;
    try { parsed = new URL(networkCameraUrl); }
    catch { networkCameraState='error'; networkCameraError='Invalid camera URL'; return; }
    const client = parsed.protocol === 'https:' ? https : http;
    networkCameraState = 'connecting';
    const req = client.get(parsed, { timeout: 7000, headers: { 'User-Agent': 'ScanCode/0.4' } }, res => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        networkCameraUrl = new URL(res.headers.location, parsed).toString();
        res.resume();
        networkCameraRetry = setTimeout(run, 100);
        return;
      }
      if (res.statusCode !== 200) {
        networkCameraState='error'; networkCameraError=`HTTP ${res.statusCode}`; res.resume(); return;
      }
      const type = String(res.headers['content-type'] || '').toLowerCase();
      const isMjpeg = type.includes('multipart') || type.includes('mjpeg');
      networkCameraState = 'connected';

      if (isMjpeg) {
        let buffer = Buffer.alloc(0);
        res.on('data', chunk => {
          buffer = Buffer.concat([buffer, chunk]);
          if (buffer.length > 8_000_000) buffer = buffer.subarray(buffer.length - 4_000_000);
          while (true) {
            const soi = buffer.indexOf(Buffer.from([0xff,0xd8]));
            if (soi < 0) { if (buffer.length > 2) buffer = buffer.subarray(buffer.length-2); break; }
            const eoi = buffer.indexOf(Buffer.from([0xff,0xd9]), soi + 2);
            if (eoi < 0) { if (soi > 0) buffer = buffer.subarray(soi); break; }
            latestNetworkFrame = Buffer.from(buffer.subarray(soi, eoi + 2));
            latestNetworkFrameAt = Date.now();
            buffer = buffer.subarray(eoi + 2);
          }
        });
        res.on('end', () => { if (networkCameraUrl) networkCameraRetry = setTimeout(run, 800); });
      } else {
        const chunks=[]; let total=0;
        res.on('data', c => { total += c.length; if (total <= 6_000_000) chunks.push(c); });
        res.on('end', () => {
          if (chunks.length && total <= 6_000_000) { latestNetworkFrame=Buffer.concat(chunks); latestNetworkFrameAt=Date.now(); networkCameraState='connected'; }
          if (networkCameraUrl) networkCameraRetry=setTimeout(run, 120);
        });
      }
    });
    networkCameraRequest = req;
    req.on('timeout', () => req.destroy(new Error('Camera connection timed out')));
    req.on('error', err => {
      networkCameraState='error'; networkCameraError=err.message || 'Camera connection failed';
      if (networkCameraUrl) networkCameraRetry=setTimeout(run, 1200);
    });
  };
  run();
}


function openBigSellerWindow() {
  const settings = readSettings();
  const targetUrl = String(settings.bigSellerUrl || '').trim();

  if (bigSellerWindow && !bigSellerWindow.isDestroyed()) {
    bigSellerWindow.show();
    bigSellerWindow.focus();
    if (targetUrl && bigSellerWindow.webContents.getURL() !== targetUrl) {
      bigSellerWindow.loadURL(targetUrl).catch(() => {});
    }
    return { ok: true, alreadyOpen: true };
  }

  bigSellerWindow = new BrowserWindow({
    width: 1200,
    height: 850,
    title: 'BigSeller — ScanCode Bridge',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true
    }
  });
  bigSellerWindow.setMenuBarVisibility(false);
  bigSellerWindow.on('closed', () => { bigSellerWindow = null; });

  if (!targetUrl) {
    bigSellerWindow.destroy();
    bigSellerWindow = null;
    return { ok:false, needsSetup:true, error:'Set the BigSeller page URL first.' };
  }

  bigSellerWindow.loadURL(targetUrl).catch(() => {});
  return { ok: true };
}

async function submitCodeToBigSeller(code) {
  const settings = readSettings();
  if (!settings.bigSellerAutoSubmit) return { ok:false, skipped:true, error:'BigSeller auto-submit is disabled.' };
  if (!bigSellerWindow || bigSellerWindow.isDestroyed()) return { ok:false, error:'BigSeller window is not open.' };

  const clean = String(code || '').trim();
  if (!clean) return { ok:false, error:'No parcel code.' };

  const script = `
    (() => {
      const code = ${JSON.stringify(clean)};
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width > 40 && r.height > 15 && r.bottom > 0 && r.right > 0 &&
          r.top < innerHeight && r.left < innerWidth &&
          s.visibility !== 'hidden' && s.display !== 'none' && !el.disabled && !el.readOnly;
      };
      const score = (el) => {
        const r = el.getBoundingClientRect();
        const text = [
          el.placeholder, el.name, el.id, el.getAttribute('aria-label'),
          el.getAttribute('data-placeholder'), el.getAttribute('title')
        ].filter(Boolean).join(' ').toLowerCase();
        let s = 0;
        if (/tracking|waybill|barcode|package|parcel|order|scan|search|logistics/.test(text)) s += 80;
        if (el.tagName === 'INPUT') s += 15;
        if (el.type === 'search' || el.type === 'text' || !el.type) s += 10;
        s += Math.max(0, 45 - (r.left / Math.max(1, innerWidth)) * 45);
        if (r.top < innerHeight * .70) s += 8;
        return s;
      };

      const candidates = [...document.querySelectorAll('input, textarea, [contenteditable="true"]')]
        .filter(visible)
        .map(el => ({el, score: score(el)}))
        .sort((a,b) => b.score - a.score);

      const target = candidates[0]?.el;
      if (!target) return {ok:false, error:'No visible BigSeller code input found.'};

      target.focus();
      if ('value' in target) {
        const proto = target.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
        if (setter) setter.call(target, code);
        else target.value = code;
      } else {
        target.textContent = code;
      }

      target.dispatchEvent(new Event('input', {bubbles:true}));
      target.dispatchEvent(new Event('change', {bubbles:true}));
      target.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true}));
      target.dispatchEvent(new KeyboardEvent('keyup', {key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true}));

      return {
        ok:true,
        tag:target.tagName,
        placeholder:target.placeholder || '',
        id:target.id || '',
        name:target.name || '',
        left:Math.round(target.getBoundingClientRect().left)
      };
    })()
  `;

  try {
    const result = await bigSellerWindow.webContents.executeJavaScript(script, true);
    return result || { ok:false, error:'BigSeller bridge returned no result.' };
  } catch (err) {
    return { ok:false, error:err.message || 'BigSeller bridge failed.' };
  }
}

async function searchServerEvidence(query) {
  const settings = readSettings();
  const root = String(settings.serverFolder || '').trim();
  const q = String(query || '').trim().toLowerCase();
  if (!q) return { ok:true, results:[] };
  if (!root) return { ok:false, error:'Server folder is not configured.', results:[] };
  if (!(await pathAccessible(root))) return { ok:false, error:'Server is offline or unavailable.', results:[] };

  const results = [];
  const walk = async (dir) => {
    let entries = [];
    try { entries = await fs.promises.readdir(dir, { withFileTypes:true }); } catch { return; }
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        await walk(full);
      } else if (entry.isFile() && entry.name.toLowerCase().includes(q)) {
        results.push({
          name: entry.name,
          path: full,
          url: pathToFileURL(full).toString(),
          ext: path.extname(entry.name).toLowerCase(),
          day: path.basename(path.dirname(full))
        });
        if (results.length >= 50) return;
      }
    }
  };
  await walk(root);
  return { ok:true, results };
}

async function endOfShiftVerification() {
  const settings = readSettings();
  const localRoot = localRecordingRoot();
  const pending = await listEvidenceFiles(localRoot);
  const pendingVideos = pending.filter(isVideoFile);

  let recovery = [];
  try {
    recovery = (await fs.promises.readdir(partialRoot())).filter(x => x.endsWith('.partial.webm'));
  } catch {}

  const serverRoot = String(settings.serverFolder || '').trim();
  const serverOnline = serverRoot ? await pathAccessible(serverRoot) : false;

  return {
    ok: pendingVideos.length === 0 && recovery.length === 0 && (!settings.autoSyncEnabled || serverOnline),
    serverConfigured: Boolean(serverRoot),
    serverOnline,
    pendingVideos: pendingVideos.length,
    pendingEvidenceFiles: pending.length,
    recoveryFiles: recovery.length,
    checkedAt: new Date().toISOString()
  };
}

async function recoverPartialRecordings() {
  const root = partialRoot();
  fs.mkdirSync(root, { recursive:true });
  let files = [];
  try { files = await fs.promises.readdir(root); } catch { return []; }
  const recovered = [];

  for (const name of files) {
    if (!name.endsWith('.partial.webm')) continue;
    const full = path.join(root, name);
    try {
      const stat = await fs.promises.stat(full);
      if (stat.size < 1024) {
        await fs.promises.unlink(full).catch(()=>{});
        continue;
      }
      const code = safeName(name.split('__')[0] || 'RECOVERED');
      const dayFolder = ensureDailyLocalFolder(new Date(stat.mtimeMs));
      const dest = await uniqueDestination(path.join(dayFolder, `${code}_RECOVERED.webm`));
      await fs.promises.rename(full, dest);
      recovered.push(dest);
    } catch {}
  }
  return recovered;
}

function restartWatchdog() {
  if (watchdogTimer) clearInterval(watchdogTimer);
  watchdogTimer = setInterval(() => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('watchdog:tick', { at: Date.now() });
    }
  }, 5000);
}





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

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 560,
    minHeight: 380,
    backgroundColor: '#101214',
    title: 'ScanCode',
    show: !SMOKE_TEST,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
      backgroundThrottling: false
    }
  });

  mainWindow.setMenuBarVisibility(false);
  mainWindow.loadFile(path.join(__dirname, 'src', 'index.html'));
  mainWindow.webContents.on('did-finish-load', () => {
    setTimeout(() => syncPendingVideos('startup'), 900);
    setTimeout(async () => {
      const recovered = await recoverPartialRecordings();
      if (recovered.length && mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('recovery:status', { recovered });
      }
    }, 500);
  });
}

app.whenReady().then(() => {
  // ScanCode is a local desktop app. Allow only media permission through
  // Electron's explicit permission handlers so webcam access is deterministic.
  session.defaultSession.setPermissionCheckHandler((webContents, permission) => permission === 'media');
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    callback(permission === 'media');
  });

  fs.mkdirSync(localRecordingRoot(), { recursive: true });
  ensureDailyLocalFolder();
  const initialSettings = readSettings();
  try {
    app.setLoginItemSettings({
      openAtLogin: Boolean(initialSettings.autoStartWithWindows),
      path: process.execPath
    });
  } catch {}

  createWindow();
  restartSyncTimer();
  restartWatchdog();
  startDailyFolderTimer();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (syncTimer) clearInterval(syncTimer);
  if (dailyFolderTimer) clearInterval(dailyFolderTimer);
  if (watchdogTimer) clearInterval(watchdogTimer);
  stopNetworkCamera();
  if (process.platform !== 'darwin') app.quit();
});

ipcMain.handle('smoke:is-enabled', () => SMOKE_TEST);
ipcMain.handle('smoke:pass', async (event, payload = {}) => {
  if (!SMOKE_TEST) return { ok:false };
  const out = path.join(process.cwd(), 'SMOKE_RUNTIME_OK.txt');
  fs.writeFileSync(out, `PASS\n${new Date().toISOString()}\n${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  setTimeout(() => app.exit(0), 150);
  return { ok:true, path:out };
});
ipcMain.handle('smoke:fail', async (event, message) => {
  if (!SMOKE_TEST) return { ok:false };
  const out = path.join(process.cwd(), 'SMOKE_RUNTIME_FAIL.txt');
  fs.writeFileSync(out, `FAIL\n${new Date().toISOString()}\n${String(message || 'Unknown smoke-test failure')}\n`, 'utf8');
  setTimeout(() => app.exit(1), 150);
  return { ok:true, path:out };
});

ipcMain.handle('camera:system-status', () => {
  let status = 'unknown';
  try { status = systemPreferences.getMediaAccessStatus('camera'); } catch {}
  return {
    platform: process.platform,
    cameraAccess: status,
    electron: process.versions.electron,
    chromium: process.versions.chrome,
    appVersion: app.getVersion()
  };
});

ipcMain.handle('settings:get', () => readSettings());

ipcMain.handle('settings:update', (event, partial) => writeSettings(partial || {}));

ipcMain.handle('settings:choose-server-folder', async () => {
  const current = readSettings();
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'Choose ScanCode server folder',
    defaultPath: current.serverFolder || undefined,
    properties: ['openDirectory', 'createDirectory']
  });

  if (result.canceled || !result.filePaths[0]) return current;
  const updated = writeSettings({ serverFolder: result.filePaths[0] });
  setTimeout(() => syncPendingVideos('server-folder-selected'), 250);
  return updated;
});


ipcMain.handle('network-camera:start', (event, url) => {
  connectNetworkCamera(url);
  return { ok: Boolean(String(url || '').trim()), url: networkCameraUrl };
});

ipcMain.handle('network-camera:stop', () => { stopNetworkCamera(); return { ok: true }; });

ipcMain.handle('network-camera:get-frame', () => ({
  state: networkCameraState,
  error: networkCameraError,
  connected: Date.now() - latestNetworkFrameAt < 2500,
  lastFrameAt: latestNetworkFrameAt,
  bytes: latestNetworkFrame ? Uint8Array.from(latestNetworkFrame) : null
}));



ipcMain.handle('recording:save', async (event, payload) => {
  const settings = readSettings();
  const started = new Date(payload.startedAt || Date.now());
  const ended = new Date(payload.endedAt || Date.now());

  const folder = path.join(settings.recordingFolder, dateFolder(started));
  fs.mkdirSync(folder, { recursive: true });

  const code = safeName(payload.code);
  const filename = `${code}.webm`;
  let filePath = path.join(folder, filename);
  let suffix = 2;

  while (fs.existsSync(filePath)) {
    filePath = path.join(folder, `${code}_${suffix}.webm`);
    suffix += 1;
  }

  const buffer = Buffer.from(payload.buffer);
  await fs.promises.writeFile(filePath, buffer);

  const metadataPath = path.join(folder, metadataFilename(payload.code));
  const metadata = {
    code: payload.code,
    startedAt: started.toISOString(),
    endedAt: ended.toISOString(),
    durationMs: Math.max(0, ended - started),
    station: settings.stationName || 'Station 01',
    operator: settings.operatorName || '',
    pc: os.hostname(),
    exception: payload.exception || null,
    details: payload.details || null,
    videoFile: path.basename(filePath),
    waybillFile: `${safeName(payload.code)}_waybill.png`,
    savedAt: new Date().toISOString()
  };
  await fs.promises.writeFile(metadataPath, JSON.stringify(metadata, null, 2), 'utf8');

  const result = {
    ok: true,
    path: filePath,
    filename: path.basename(filePath),
    metadataPath,
    code: payload.code,
    startedAt: started.toISOString(),
    endedAt: ended.toISOString(),
    bytes: buffer.length,
    localFolder: settings.recordingFolder
  };

  setTimeout(() => syncPendingVideos('new-recording'), 300);
  return result;
});


ipcMain.handle('snapshot:save', async (event, payload) => {
  const settings = readSettings();
  const when = new Date(payload.capturedAt || Date.now());
  const folder = path.join(settings.recordingFolder, dateFolder(when));
  fs.mkdirSync(folder, { recursive: true });

  const base = imageFilenameBase(payload.code);
  let filePath = path.join(folder, `${base}.png`);
  let suffix = 2;

  while (fs.existsSync(filePath)) {
    filePath = path.join(folder, `${base}_${suffix}.png`);
    suffix += 1;
  }

  const buffer = Buffer.from(payload.buffer);
  await fs.promises.writeFile(filePath, buffer);

  return {
    ok: true,
    path: filePath,
    filename: path.basename(filePath),
    code: payload.code,
    capturedAt: when.toISOString(),
    bytes: buffer.length
  };
});



ipcMain.handle('bigseller:open', () => openBigSellerWindow());
ipcMain.handle('bigseller:submit', (event, code) => submitCodeToBigSeller(code));
ipcMain.handle('evidence:search', (event, query) => searchServerEvidence(query));
ipcMain.handle('shift:verify', () => endOfShiftVerification());

ipcMain.handle('recovery:start', async (event, payload) => {
  const root = partialRoot();
  fs.mkdirSync(root, { recursive:true });
  const sessionId = safeName(payload.sessionId || crypto.randomBytes(8).toString('hex'));
  const filePath = path.join(root, `${safeName(payload.code)}__${sessionId}.partial.webm`);
  await fs.promises.writeFile(filePath, Buffer.alloc(0));
  return { ok:true, filePath };
});

ipcMain.handle('recovery:append', async (event, payload) => {
  if (!payload?.filePath || !payload?.buffer) return { ok:false };
  const base = path.resolve(partialRoot());
  const target = path.resolve(payload.filePath);
  if (!target.startsWith(base)) return { ok:false, error:'Invalid recovery path.' };
  await fs.promises.appendFile(target, Buffer.from(payload.buffer));
  return { ok:true };
});

ipcMain.handle('recovery:finish', async (event, payload) => {
  if (!payload?.filePath) return { ok:false };
  await fs.promises.unlink(payload.filePath).catch(()=>{});
  return { ok:true };
});

ipcMain.handle('folder:open-recordings', async () => {
  const folder = localRecordingRoot();
  fs.mkdirSync(folder, { recursive: true });
  await shell.openPath(folder);
  return true;
});

ipcMain.handle('folder:open-server', async () => {
  const serverFolder = String(readSettings().serverFolder || '').trim();
  if (!serverFolder) return { ok: false, error: 'Server folder is not configured.' };
  const reachable = await pathAccessible(serverFolder);
  if (!reachable) return { ok: false, error: 'Server folder is offline or unavailable.' };
  await shell.openPath(serverFolder);
  return { ok: true };
});

ipcMain.handle('sync:now', () => syncPendingVideos('manual'));

ipcMain.handle('file:show', async (event, filePath) => {
  if (filePath && fs.existsSync(filePath)) shell.showItemInFolder(filePath);
  return true;
});

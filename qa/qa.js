const fs = require('fs');
const path = require('path');
const cp = require('child_process');
const root = path.resolve(__dirname, '..');
const read = p => fs.readFileSync(path.join(root,p),'utf8');
const html = read('src/index.html');
const renderer = read('src/renderer.js');
const main = read('main.js');
const pkg = JSON.parse(read('package.json'));
let pass=0, fail=0, setup=0;
const rows=[];
function result(name,status,detail='') { rows.push({name,status,detail}); if(status==='PASS') pass++; else if(status==='FAIL') fail++; else setup++; }
function check(name,cond,detail='') { result(name,cond?'PASS':'FAIL',detail); }

// Syntax
for (const f of ['main.js','src/renderer.js']) {
  const r=cp.spawnSync(process.execPath,['--check',path.join(root,f)],{encoding:'utf8'});
  check(`JavaScript syntax: ${f}`,r.status===0,(r.stderr||'').trim());
}

// HTML / renderer wiring
const ids=[...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1]);
check('No duplicate HTML IDs', new Set(ids).size===ids.length);
const refs=[...renderer.matchAll(/\$\('([^']+)'\)/g)].map(m=>m[1]);
const missingRefs=[...new Set(refs.filter(x=>!ids.includes(x)))];
check('All renderer element refs exist', missingRefs.length===0, missingRefs.join(', '));
check('Uninstall button removed from app UI', !html.includes('id="uninstallBtn"') && !renderer.includes('els.uninstallBtn'));
check('Compact View removed from UI/runtime', !html.includes('compactModeBtn') && !renderer.includes('toggleCompactMode') && !main.includes('window:set-compact'));
check('Camera device selector has a visible fallback', html.includes('Default / Built-in Camera') && renderer.includes('getUserMediaWithTimeout'));
check('Recording controls wired', ['startVideoBtn','pauseVideoBtn','stopVideoBtn'].every(id=>renderer.includes(`els.${id}`)));
check('Camera device enumeration is wired', renderer.includes('enumerateDevices') && renderer.includes('loadCameraList'));
const initBlock = (renderer.match(/async function init\(\) \{[\s\S]*?\n\}/) || [''])[0];
check('Camera startup avoids temporary probe stream', !initBlock.includes('const probe = await navigator.mediaDevices.getUserMedia') && renderer.includes('localCameraStream') && renderer.includes('getUserMediaWithTimeout'));
check('Built-in/USB camera is the default startup path', initBlock.includes("settings.cameraMode = 'local'") && initBlock.includes("await startCamera('');"));
check('F1/F2/F3 recording shortcuts wired', ['F1','F2','F3'].every(k=>renderer.includes(`event.key === '${k}'`)) && !renderer.includes("event.key === 'F4'"));

// IPC parity
const invokes=[...renderer.matchAll(/ipcRenderer\.invoke\(['"]([^'"]+)/g)].map(m=>m[1]);
const handlers=[...main.matchAll(/ipcMain\.handle\(['"]([^'"]+)/g)].map(m=>m[1]);
const missingIPC=[...new Set(invokes.filter(x=>!handlers.includes(x)))];
check('All renderer IPC calls have main handlers', missingIPC.length===0, missingIPC.join(', '));

// Core feature presence
check('Daily Documents\\ScanCode storage', main.includes("app.getPath('documents')") && main.includes("'ScanCode'"));
check('QR/barcode filename based video save', main.includes('`${code}.webm`'));
check('Waybill snapshot save', main.includes("ipcMain.handle('snapshot:save'") && renderer.includes('saveWaybillSnapshot'));
check('Crash recovery handlers', ['recovery:start','recovery:append','recovery:finish'].every(x=>main.includes(x)));
check('Server SHA-256 verification', main.includes('sha256File') && main.includes('tempHash') && main.includes('srcHash'));
check('Server verified local deletion rule', main.includes('fs.promises.unlink(localFile)'));
check('Camera quality check', renderer.includes('evaluateCameraQuality'));
check('Camera watchdog', renderer.includes("ipcRenderer.on('watchdog:tick'"));
check('Scan confidence confirmation', renderer.includes('scanConfirmations') && renderer.includes('scanCandidate'));
check('Barcode filtering', renderer.includes('formatAllowed') && renderer.includes('barcodeFilter'));
check('Success scan sound', renderer.includes('beepSuccess'));
check('End-of-shift verification', main.includes('endOfShiftVerification') && renderer.includes('endShiftBtn'));
check('Server parcel search/playback', main.includes('searchServerEvidence') && renderer.includes('runServerSearch'));
check('Standalone uninstall script exists', fs.existsSync(path.join(root,'UNINSTALL_SCANCODE.bat')));
check('Installer script exists', fs.existsSync(path.join(root,'INSTALL_SCANCODE.bat')));
check('Author metadata', pkg.author==='John Mark Bataller' && pkg.build?.extraMetadata?.author==='John Mark Bataller');
check('Electron build config has NSIS + portable', JSON.stringify(pkg.build?.win?.target||[]).includes('nsis') && JSON.stringify(pkg.build?.win?.target||[]).includes('portable'));

check('Secure ScanCode renderer origin', main.includes('registerSchemesAsPrivileged') && main.includes("scancode://app/index.html") && main.includes("secure: true"));
check('Camera watchdog cannot interrupt startup', renderer.includes('watchdogRestarting || cameraStarting') && renderer.includes('cameraLastFailureAt'));
check('Camera request timeout is self-cleaning', renderer.includes('clearTimeout(timer)') && renderer.includes('getUserMediaWithTimeout'));

// Environment-dependent features
result('Camera hardware + Windows camera permission','NEEDS SETUP','Must be verified on each warehouse PC/camera.');
result('BigSeller exact field/result extraction','NEEDS SETUP','Needs the exact BigSeller warehouse page URL/DOM; current bridge is guarded until URL is set.');
result('Central server transfer/playback','NEEDS SETUP','Requires the real UNC server path and credentials/network access.');
result('Phone/network camera','NEEDS SETUP','Requires a reachable MJPEG/JPEG camera URL.');

console.log('\nScanCode QA Report');
console.log('='.repeat(72));
for(const r of rows) console.log(`${r.status.padEnd(11)} ${r.name}${r.detail?` — ${r.detail}`:''}`);
console.log('='.repeat(72));
console.log(`PASS: ${pass}   FAIL: ${fail}   NEEDS SETUP: ${setup}`);
process.exitCode=fail?1:0;

check('Complete Electron media permission handling', main.includes('setPermissionCheckHandler') && main.includes('setPermissionRequestHandler'));

const fs=require('fs'),path=require('path'),cp=require('child_process');
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

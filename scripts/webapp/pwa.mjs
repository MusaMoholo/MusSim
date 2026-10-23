import {read,importBundle,cleanupInterruptedImport} from './pwa-storage.mjs';
import {staticRequest} from './static-api.mjs';

export async function start(boot){
 window.MUSSIM_STATIC=true;
 const originalFetch=window.fetch.bind(window);
 window.fetch=(input,options)=>{const u=new URL(typeof input==='string'?input:input.url,location.href);return u.origin===location.origin&&u.pathname.startsWith('/api/')?staticRequest(u.href,options):originalFetch(input,options);};
 const panel=document.createElement('details');panel.className='panel mussim-data';panel.id='mussim-data';panel.setAttribute('aria-label','MusSim data and installation');
 panel.innerHTML=`<div class="row"><div class="mussim-data-copy"><strong id="mussim-data-title">Your dashboard, on this device</strong><p id="mussim-data-status" class="note" role="status" aria-live="polite">Checking saved data…</p></div><button id="mussim-import">Import data</button></div><input id="mussim-file" type="file" accept=".gz,.mussim,application/gzip,application/octet-stream" hidden><progress id="mussim-import-progress" aria-label="Importing data" hidden></progress><p id="mussim-import-error" class="note err" role="alert" hidden></p><details id="mussim-install"><summary>Install &amp; updates</summary><p class="note">On iPhone, open this address in Safari, tap Share, then Add to Home Screen. Open MusSim from its icon and import your data there. Safari and the installed app may keep separate data.</p><p class="note">After nightly finishes on your Mac, import the latest .mussim.gz file from Files → iCloud Drive. Imported data stays on this device; it is never uploaded. Keep the export as a backup if browser storage is cleared.</p><p id="mussim-offline-status" class="note" role="status">Preparing offline app…</p><button id="mussim-update" class="ghost" hidden>Update app</button></details>`;
 panel.insertAdjacentHTML('afterbegin','<summary>Offline data &amp; installation</summary>');
 document.querySelector('.snapshot-toolbar').before(panel);
 document.querySelector('#livetoggle').hidden=true;
 const input=panel.querySelector('#mussim-file'),button=panel.querySelector('#mussim-import'),status=panel.querySelector('#mussim-data-status'),error=panel.querySelector('#mussim-import-error'),progress=panel.querySelector('progress');
 button.disabled=true;
 button.onclick=()=>input.click();
 let importing=false,wake;
 const keepAwake=async()=>{if(importing&&document.visibilityState==='visible')try{wake=await navigator.wakeLock?.request('screen');}catch{}};
 document.addEventListener('visibilitychange',keepAwake);
 input.onchange=async()=>{const file=input.files?.[0];if(!file)return;button.disabled=true;importing=true;await keepAwake();error.hidden=true;progress.hidden=false;status.textContent='Importing… keep MusSim open and the screen unlocked until this finishes.';try{
   const result=await importBundle(file,({count,savedMegabytes,added,reused})=>{status.textContent=`Importing… ${count.toLocaleString()} checked · ${added.toLocaleString()} new · ${reused.toLocaleString()} reused · ${savedMegabytes.toFixed(0)} MB added. Keep MusSim open and unlocked.`;});
   await navigator.storage?.persist?.().catch(()=>false);
   status.textContent=`Imported ${result.latest}. Opening dashboard…`;button.disabled=false;location.reload();
  }catch(e){error.textContent=e.name==='QuotaExceededError'?'Not enough device storage. Your previous import is unchanged. Free some space and try again.':`${e.message} (${e.name||'Error'}). Any previous import is unchanged.`;error.hidden=false;status.textContent='Import failed. Any previous data is still available.';button.disabled=false;progress.hidden=true;input.value='';}
  finally{importing=false;await wake?.release().catch(()=>{});wake=null;}
 };
 window.addEventListener('beforeunload',e=>{if(button.disabled){e.preventDefault();e.returnValue='';}});
 let active;
 await cleanupInterruptedImport().catch(()=>{});
 try{active=await read('meta','active');if(active){const info=await read('meta',active);status.textContent=`Saved through snapshot ${info.latest} · ${info.snapshots.length} browsing dates · works offline`;button.textContent='Import latest data';await boot();}else{panel.open=true;status.textContent='Import your .mussim.gz bundle from Files → iCloud Drive to open your dashboard.';document.querySelector('.snapshot-toolbar').hidden=true;panel.querySelector('details').open=true;}}
 catch(e){status.textContent='Device storage is unavailable.';error.hidden=false;error.textContent=e.message;}
 button.disabled=false;
 const offline=panel.querySelector('#mussim-offline-status');
 if('serviceWorker'in navigator){try{
  const registration=await navigator.serviceWorker.register(new URL('../sw.js',import.meta.url),{type:'module',updateViaCache:'none'});
  await navigator.serviceWorker.ready;
  offline.textContent='App saved for offline use. Data is saved when you import it.';
  const offer=()=>{if(!registration.waiting)return;panel.querySelector('summary').textContent='App update available · Offline data & installation';const update=panel.querySelector('#mussim-update');update.hidden=false;update.onclick=()=>{if(button.disabled)return;registration.waiting.postMessage({type:'ACTIVATE'});};};
  offer();registration.addEventListener('updatefound',()=>{const worker=registration.installing;worker?.addEventListener('statechange',()=>{if(worker.state==='installed')offer();});});
  let changing=false;navigator.serviceWorker.addEventListener('controllerchange',()=>{if(navigator.serviceWorker.controller&&changing)location.reload();changing=true;});
  // On an already controlled page, a controller change is an explicit app update.
  changing=Boolean(navigator.serviceWorker.controller);
 }catch(e){offline.textContent='Offline app setup failed: '+e.message+'. Keep an internet connection and try reloading.';offline.setAttribute('role','alert');}}
 else{offline.textContent='Offline installation requires a supported browser and HTTPS.';offline.setAttribute('role','alert');}
}

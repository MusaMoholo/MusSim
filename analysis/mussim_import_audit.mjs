// Optional Playwright acceptance: Safari-engine writes, rollback and complete phone bundle.
// MUSSIM_PLAYWRIGHT can point to an isolated installation's index.mjs.
import {mkdirSync,writeFileSync} from 'node:fs';
const {webkit,chromium}=await import(process.env.MUSSIM_PLAYWRIGHT||'playwright');
const [engine='webkit',bundle='/private/tmp/MusSim-phone.mussim.gz',app='http://127.0.0.1:8777/MusSim/']=process.argv.slice(2);
const dir='/private/tmp/mussim-import-audit-'+engine+'-'+Date.now();mkdirSync(dir);
const browser=await ({webkit,chromium}[engine]).launch();
const context=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
const page=await context.newPage(),exceptions=[];page.on('pageerror',e=>exceptions.push(String(e)));
let checks=0;const assert=(ok,message)=>{checks++;if(!ok)throw Error(message);};
try{
 await page.goto(app);await page.waitForFunction(()=>document.querySelector('#mussim-import')?.disabled===false);
 const faults=await page.evaluate(async()=>{
  const m=await import('./assets/pwa-storage.mjs'),results={};
  const original=IDBObjectStore.prototype.put;
  try{
   let calls=0;IDBObjectStore.prototype.put=function(...args){calls++;const r=original.apply(this,args);if(calls===1)this.transaction.abort();return r;};
   await m.write('meta','audit-retry',{ok:true});results.retry=calls===2&&(await m.read('meta','audit-retry')).ok;
   calls=0;IDBObjectStore.prototype.put=function(...args){calls++;const r=original.apply(this,args);this.transaction.abort();return r;};
   let name='';try{await m.write('meta','audit-abort',true);}catch(e){name=e.name;}
   results.abort=name==='AbortError'&&calls===3&&await m.read('meta','audit-abort')===undefined;
   calls=0;IDBObjectStore.prototype.put=function(){calls++;throw new DOMException('Injected storage quota','QuotaExceededError');};
   name='';try{await m.write('meta','audit-quota',true);}catch(e){name=e.name;}
   results.quota=name==='QuotaExceededError'&&calls===1&&await m.read('meta','audit-quota')===undefined;
  }finally{IDBObjectStore.prototype.put=original;}
  const text='backward-compatible evidence '.repeat(200);
  const blob=await new Response(new Response(text).body.pipeThrough(new CompressionStream('gzip'))).blob();
  let blobWriteFailure=null;
  try{await m.write('records','audit|blob',{bodyGzip:blob});results.legacyBlob=(await m.stored('blob','audit')).body===text;}catch(e){blobWriteFailure=e.name+': '+e.message;}
  await m.write('records','audit|bytes',{bodyGzip:new Uint8Array(await blob.arrayBuffer())});
  results.byteRoundtrip=(await m.stored('bytes','audit')).body===text;
  const digest=async data=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data)),v=>v.toString(16).padStart(2,'0')).join('');
  const record=async(key,value)=>{const body=JSON.stringify(value);return {key,body,status:200,type:'application/json',sha256:await digest(new TextEncoder().encode(body))};};
  const header={format:'mussim',version:1,latest:'2026-10-23',snapshots:['2026-10-23']};
  const rows=await Promise.all([record('/api/meta',{snapshots:[{date:header.latest}]}),record('/api/badges',{}),record('/material/index',[]),record('/api/snapshot?date='+header.latest,{})]);
  const file=async lines=>new Response(new Blob([lines.map(v=>JSON.stringify(v)).join('\n')+'\n']).stream().pipeThrough(new CompressionStream('gzip'))).blob();
  await m.importBundle(await file([header,...rows,{end:true,records:rows.length}]));
  results.v1=!!await m.read('meta','active');
  const repeat=await m.importBundle(await file([header,...rows,{end:true,records:rows.length}]));
  results.unchanged=repeat.added===0&&repeat.reused===rows.length&&repeat.savedBytes===0;
  const changedRows=[...rows];changedRows[1]=await record('/api/badges',{probe:1});
  const changed=await m.importBundle(await file([header,...changedRows,{end:true,records:rows.length}]));
  results.changed=changed.added===1&&changed.reused===rows.length-1&&JSON.parse((await m.stored('/api/badges')).body).probe===1;
  const active=await m.read('meta','active');
  let refused=false;try{await m.importBundle(await file([header,...rows]));}catch{refused=true;}
  results.truncated=refused&&active===await m.read('meta','active');
  const packed={...rows[0],body:undefined,body_gzip:btoa(String.fromCharCode(...new Uint8Array(await blob.arrayBuffer()))),packed_sha256:'0'.repeat(64)};
  refused=false;try{await m.importBundle(await file([{...header,version:2},packed,{end:true,records:1}]));}catch(e){refused=e.message.includes('checksum');}
  results.checksum=refused&&active===await m.read('meta','active');
  const brokenRows=[...rows];for(let i=0;i<50;i++)brokenRows.push(await record('/material/fault-'+i,{}));
  try{
   IDBObjectStore.prototype.put=function(...args){if(this.name==='records')throw new DOMException('Injected quota during staged import','QuotaExceededError');return original.apply(this,args);};
   refused=false;try{await m.importBundle(await file([header,...brokenRows,{end:true,records:brokenRows.length}]));}catch(e){refused=e.name==='QuotaExceededError';}
  }finally{IDBObjectStore.prototype.put=original;}
  results.rollback=refused&&active===await m.read('meta','active')&&await m.read('meta','pending')===null;
  await m.removeGeneration('audit');return {results,blobWriteFailure};
 });
 for(const [name,ok] of Object.entries(faults.results))assert(ok,'Fault/compatibility check: '+name);
 // Exercise the real UI wake-lock request and release even in a headless engine.
 await page.evaluate(()=>{window.auditWake={requested:0,released:0};Object.defineProperty(navigator,'wakeLock',{configurable:true,value:{request:async()=>{window.auditWake.requested++;return {release:async()=>{window.auditWake.released++;}};}}});});
 const start=Date.now();await page.locator('#mussim-file').setInputFiles(bundle);
 await page.waitForFunction(()=>window.auditWake.requested===1);
 assert(await page.locator('#mussim-import').isDisabled(),'Import excludes concurrent selection');
 await page.waitForFunction(()=>document.querySelector('#mussim-data-status')?.textContent.includes('MB added'),{},{timeout:120000});
 await page.screenshot({path:dir+'/progress.png'});
 // Wait for commit and request release before navigation clears audit state.
 await page.waitForFunction(()=>window.auditWake?.released===1||document.querySelector('#mussim-data-status')?.textContent.includes('snapshot 2026-10-23'),{},{timeout:900000});
 await page.waitForFunction(()=>document.querySelector('#mussim-data-status')?.textContent.includes('snapshot 2026-10-23'),{},{timeout:900000});
 const seconds=(Date.now()-start)/1000;
 const saved=await page.evaluate(async()=>{
  const m=await import('./assets/pwa-storage.mjs'),active=await m.read('meta','active'),meta=await m.read('meta',active),db=await m.database();let count=0,bytes=0,blobs=0;
   try{for(const [low,high] of [[active+'|',active+'|\uffff'],['content|','content|\uffff']])await new Promise((resolve,reject)=>{const tx=db.transaction('records');const req=tx.objectStore('records').openCursor(IDBKeyRange.bound(low,high));req.onsuccess=()=>{const c=req.result;if(!c)return;if(low!=='content|')count++;const v=c.value;blobs+=v.bodyGzip instanceof Blob;bytes+=v.bodyGzip?.byteLength||new TextEncoder().encode(v.body||'').length;c.continue();};tx.oncomplete=resolve;tx.onabort=()=>reject(tx.error);});}finally{db.close();}
  const players=await m.stored('/api/players?date='+meta.latest);const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(players.body))),v=>v.toString(16).padStart(2,'0')).join('');
  return {count,bytes,blobs,dates:meta.snapshots.length,version:meta.version,added:meta.added,reused:meta.reused,largestPlayerHash:digest===players.sha256,quota:await navigator.storage?.estimate?.()};
 });
 assert(saved.count===64468&&saved.dates===84,'Complete retained bundle accounting');assert(saved.version===2&&saved.blobs===0,'Precompressed byte-array storage');assert(saved.largestPlayerHash,'Largest player payload independently matches source checksum');
 await page.locator('#mussim-file').setInputFiles(bundle);
 await page.waitForFunction(()=>document.querySelector('#mussim-data-status')?.textContent.includes('snapshot 2026-10-23')&&!document.querySelector('#mussim-import').disabled,{},{timeout:900000});
 const repeat=await page.evaluate(async()=>{const m=await import('./assets/pwa-storage.mjs');return m.read('meta',await m.read('meta','active'));});
 assert(repeat.added===0&&repeat.reused===64468&&repeat.savedBytes===0,'Full bundle repeat writes zero existing payloads');
 for(const colorScheme of ['light','dark']){await page.emulateMedia({colorScheme});await page.evaluate(t=>document.documentElement.dataset.theme=t,colorScheme);await page.screenshot({path:dir+'/'+colorScheme+'.png'});}
 await page.waitForFunction(()=>!!navigator.serviceWorker.controller);await context.setOffline(true);await page.reload();await page.waitForFunction(()=>typeof RESULT!=='undefined'&&RESULT?.source?.date==='2026-10-23');assert(await page.title()==='MusSim','Offline cold launch');assert(exceptions.length===0,'No browser exceptions: '+exceptions);
 const result={engine,checks,seconds,saved,repeat:{added:repeat.added,reused:repeat.reused,savedBytes:repeat.savedBytes},faults,exceptions,dir};writeFileSync(dir+'/result.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
}catch(e){console.error('Evidence: '+dir);await page.screenshot({path:dir+'/failure.png'}).catch(()=>{});throw e;}finally{await browser.close();}

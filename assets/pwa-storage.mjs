// Shared by the page and service worker. A new import becomes visible only at commit.
export const DB_NAME='mussim-data-v1';
export function database(){return new Promise((resolve,reject)=>{const r=indexedDB.open(DB_NAME,1);r.onupgradeneeded=()=>{r.result.createObjectStore('records');r.result.createObjectStore('meta');};r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
export async function read(store,key){const db=await database();try{return await new Promise((resolve,reject)=>{const tx=db.transaction(store);const r=tx.objectStore(store).get(key);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}finally{db.close();}}
export async function write(store,key,value){const db=await database();try{return await new Promise((resolve,reject)=>{const tx=db.transaction(store,'readwrite');tx.objectStore(store).put(value,key);tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||Error('Storage write was interrupted.'));});}finally{db.close();}}
export async function removeGeneration(generation){const db=await database();try{return await new Promise((resolve,reject)=>{const tx=db.transaction('records','readwrite');tx.objectStore('records').delete(IDBKeyRange.bound(generation+'|',generation+'|\uffff'));tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});}finally{db.close();}}
export async function stored(key,generation){const active=generation||await read('meta','active');const record=active?await read('records',active+'|'+key):undefined;if(record?.bodyGzip)return {...record,body:await new Response(record.bodyGzip.stream().pipeThrough(new DecompressionStream('gzip'))).text()};return record;}
export function recordResponse(record){if(!record)return new Response(JSON.stringify({error:'This evidence is not in the imported bundle.'}),{status:404,headers:{'Content-Type':'application/json'}});const body=record.binary?Uint8Array.from(atob(record.body),c=>c.charCodeAt(0)):record.body;return new Response(body,{status:record.status,headers:{'Content-Type':record.type}});}

export async function cleanupInterruptedImport(){
 if(!navigator.locks)return;
 await navigator.locks.request('mussim-import',{ifAvailable:true},async lock=>{if(!lock)return;const pending=await read('meta','pending'),active=await read('meta','active');if(pending&&pending!==active)await removeGeneration(pending);await write('meta','pending',null);});
}
export async function importBundle(file,onProgress=()=>{}){
 if(navigator.locks)return navigator.locks.request('mussim-import',{ifAvailable:true},lock=>{if(!lock)throw Error('An import is already running in another MusSim window.');return importLocked(file,onProgress);});
 return importLocked(file,onProgress);
}
async function importLocked(file,onProgress){
 if(!globalThis.DecompressionStream)throw Error('This browser cannot unpack the data bundle. Update iOS/Safari and try again.');
 const generation=crypto.randomUUID(),previous=await read('meta','active');let header=null,count=0,ended=false,buffer='',total=0;
 const seen=new Set();
 await write('meta','pending',generation);
 try{
  const stream=file.stream().pipeThrough(new DecompressionStream('gzip')).pipeThrough(new TextDecoderStream());
  for await(const part of stream){
   total+=part.length;if(total>8_000_000_000)throw Error('Data bundle exceeds the supported import size.');buffer+=part;
   let at;
   while((at=buffer.indexOf('\n'))>=0){
    const line=buffer.slice(0,at);buffer=buffer.slice(at+1);if(!line.trim())continue;if(ended)throw Error('Unexpected content after the bundle footer.');
    const item=JSON.parse(line);
    if(!header){if(item.format!=='mussim'||item.version!==1||!Array.isArray(item.snapshots)||!item.snapshots.length||item.snapshots.some(d=>typeof d!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(d))||new Set(item.snapshots).size!==item.snapshots.length||[...item.snapshots].sort().join('|')!==item.snapshots.join('|')||!item.snapshots.includes(item.latest))throw Error('Choose a supported MusSim data bundle.');header=item;continue;}
    if(item.end){if(item.records!==count)throw Error('Incomplete data bundle.');ended=true;continue;}
    if(typeof item.key!=='string'||!/^\/(api\/|material\/|badges\/\d+\.png$)/.test(item.key)||seen.has(item.key)||typeof item.body!=='string'||![200,400,404,409,422,503].includes(item.status)||!['application/json','image/png'].includes(item.type))throw Error('Invalid or duplicate bundle record.');
    const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(item.body))),v=>v.toString(16).padStart(2,'0')).join('');
    if(digest!==item.sha256)throw Error('Data checksum failed. Export and import a fresh bundle.');
    // Retain compressed evidence on disk. A full season otherwise expands to gigabytes.
    let record=item;
    if(item.body.length>8192&&globalThis.CompressionStream){const bodyGzip=await new Response(new Blob([item.body]).stream().pipeThrough(new CompressionStream('gzip'))).blob();record={...item,body:undefined,bodyGzip};}
    await write('records',generation+'|'+item.key,record);seen.add(item.key);count++;
    if(count%25===0){onProgress({count,megabytes:total/1e6});await new Promise(r=>setTimeout(r,0));}
   }
  }
  if(!ended||buffer.trim())throw Error('The data bundle is truncated. Your previous data is still available.');
  for(const key of ['/api/meta','/api/badges','/material/index',...header.snapshots.map(d=>'/api/snapshot?date='+d)])if(!seen.has(key))throw Error('The bundle is missing required dashboard data.');
  const meta=JSON.parse((await stored('/api/meta',generation)).body);
  if(meta.snapshots.map(r=>r.date).join('|')!==header.snapshots.join('|'))throw Error('Bundle snapshot catalogue does not match its manifest.');
  // Keep metadata with its generation; the single active pointer is the commit boundary.
  await write('meta',generation,header);await write('meta','active',generation);
  // Cleanup cannot turn a successful commit into a reported failed import.
  try{await write('meta','pending',null);const retired=await read('meta','previous');await write('meta','previous',previous||null);if(retired&&retired!==previous)await removeGeneration(retired);}catch{}
  return {...header,count};
 }catch(error){await removeGeneration(generation).catch(()=>{});await write('meta','pending',null).catch(()=>{});throw error;}
}

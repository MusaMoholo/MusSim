// Shared by the page and service worker. A new import becomes visible only at commit.
export const DB_NAME='mussim-data-v1';
export function database(){return new Promise((resolve,reject)=>{const r=indexedDB.open(DB_NAME,1);r.onupgradeneeded=()=>{r.result.createObjectStore('records');r.result.createObjectStore('meta');};r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
export async function read(store,key){const db=await database();try{return await new Promise((resolve,reject)=>{const tx=db.transaction(store);const r=tx.objectStore(store).get(key);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}finally{db.close();}}
// Byte arrays avoid Safari's file-backed Blob writes. Bounded batches also avoid
// opening a database and committing a transaction for every individual record.
export async function writeBatch(store,entries){
 for(let attempt=0;;attempt++){
  let db;
  try{db=await database();await new Promise((resolve,reject)=>{
   const tx=db.transaction(store,'readwrite');let failure;
   tx.oncomplete=()=>resolve();tx.onerror=e=>{failure=e.target.error||tx.error;};
   tx.onabort=()=>reject(failure||tx.error||new DOMException('Storage write was interrupted.','AbortError'));
   try{for(const [key,value] of entries)tx.objectStore(store).put(value,key);}catch(e){tx.abort();reject(e);}
  });return;
  }catch(e){if(e.name!=='AbortError'||attempt>=2)throw e;await new Promise(r=>setTimeout(r,150*(attempt+1)));}
  finally{db?.close();}
 }
}
export function write(store,key,value){return writeBatch(store,[[key,value]]);}
export async function removeGeneration(generation){const db=await database();try{return await new Promise((resolve,reject)=>{const tx=db.transaction('records','readwrite');tx.objectStore('records').delete(IDBKeyRange.bound(generation+'|',generation+'|\uffff'));tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});}finally{db.close();}}
export async function stored(key,generation){const active=generation||await read('meta','active');let record=active?await read('records',active+'|'+key):undefined;if(record?.contentKey){const content=await read('records',record.contentKey);if(!content)throw Error('Saved data is incomplete. Import your bundle again.');record={...record,...content};}if(record?.bodyGzip)return {...record,body:await new Response(new Response(record.bodyGzip).body.pipeThrough(new DecompressionStream('gzip'))).text()};return record;}
async function contentKeys(){const db=await database();try{return await new Promise((resolve,reject)=>{const r=db.transaction('records').objectStore('records').getAllKeys(IDBKeyRange.bound('content|','content|\uffff'));r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}finally{db.close();}}
async function pruneContent(generations){
 const keep=new Set(),db=await database();
 try{for(const generation of generations.filter(Boolean))await new Promise((resolve,reject)=>{const tx=db.transaction('records'),r=tx.objectStore('records').openCursor(IDBKeyRange.bound(generation+'|',generation+'|\uffff'));r.onsuccess=()=>{const c=r.result;if(c){if(c.value.contentKey)keep.add(c.value.contentKey);c.continue();}};tx.oncomplete=resolve;tx.onabort=()=>reject(tx.error);});
  const obsolete=(await contentKeys()).filter(k=>!keep.has(k));
  for(let start=0;start<obsolete.length;start+=250)await new Promise((resolve,reject)=>{const tx=db.transaction('records','readwrite');for(const key of obsolete.slice(start,start+250))tx.objectStore('records').delete(key);tx.oncomplete=resolve;tx.onabort=()=>reject(tx.error);});
 }finally{db.close();}
}
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
 const generation=crypto.randomUUID(),previous=await read('meta','active'),existing=new Set(await contentKeys());let header=null,count=0,ended=false,buffer=[],total=0,saved=0,added=0,reused=0,batch=[],batchBytes=0;
 const flush=async()=>{if(!batch.length)return;await writeBatch('records',batch);batch=[];batchBytes=0;onProgress({count,megabytes:total/1e6,savedMegabytes:saved/1e6,added,reused});await new Promise(r=>setTimeout(r,0));};
 const seen=new Set();
 await write('meta','pending',generation);
 try{
  const stream=file.stream().pipeThrough(new DecompressionStream('gzip')).pipeThrough(new TextDecoderStream());
  for await(const part of stream){
   total+=part.length;if(total>8_000_000_000)throw Error('Data bundle exceeds the supported import size.');
   let at,cursor=0;
   while((at=part.indexOf('\n',cursor))>=0){
    let line;if(buffer.length){buffer.push(part.slice(cursor,at));line=buffer.join('');buffer=[];}else line=part.slice(cursor,at);cursor=at+1;
    if(!line.trim())continue;if(ended)throw Error('Unexpected content after the bundle footer.');
    const item=JSON.parse(line);line=null;
    if(!header){if(item.format!=='mussim'||![1,2].includes(item.version)||!Array.isArray(item.snapshots)||!item.snapshots.length||item.snapshots.some(d=>typeof d!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(d))||new Set(item.snapshots).size!==item.snapshots.length||[...item.snapshots].sort().join('|')!==item.snapshots.join('|')||!item.snapshots.includes(item.latest))throw Error('Choose a supported MusSim data bundle.');header=item;continue;}
    if(item.end){if(item.records!==count)throw Error('Incomplete data bundle.');ended=true;continue;}
    const packed=header.version===2&&typeof item.body_gzip==='string';
    if(typeof item.key!=='string'||!/^\/(api\/|material\/|badges\/\d+\.png$)/.test(item.key)||seen.has(item.key)||(!packed&&typeof item.body!=='string')||!/^[a-f0-9]{64}$/.test(item.sha256)||![200,400,404,409,422,503].includes(item.status)||!['application/json','image/png'].includes(item.type))throw Error('Invalid or duplicate bundle record.');
    const data=packed?Uint8Array.from(atob(item.body_gzip),c=>c.charCodeAt(0)):new TextEncoder().encode(item.body);
    const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data)),v=>v.toString(16).padStart(2,'0')).join('');
    if(digest!==(packed?item.packed_sha256:item.sha256))throw Error('Data checksum failed. Export and import a fresh bundle.');
    // Retain compressed evidence on disk. A full season otherwise expands to gigabytes.
    const contentKey='content|'+(packed?'gzip|':'raw|')+digest;
    if(existing.has(contentKey))reused++;
    else{
     let content;
     if(packed)content={bodyGzip:data};
     else if(item.body.length>1024&&globalThis.CompressionStream)content={bodyGzip:new Uint8Array(await new Response(new Response(data).body.pipeThrough(new CompressionStream('gzip'))).arrayBuffer())};
     else content={body:item.body};
     const bytes=content.bodyGzip?.byteLength??data.byteLength;
     batch.push([contentKey,content]);batchBytes+=bytes;saved+=bytes;added++;existing.add(contentKey);
    }
    const {body,body_gzip,packed_sha256,...metadata}=item;
    batch.push([generation+'|'+item.key,{...metadata,contentKey}]);seen.add(item.key);count++;
    if(batch.length>=100||batchBytes>=1_000_000)await flush();
   }
   if(cursor<part.length)buffer.push(part.slice(cursor));
  }
  if(!ended||buffer.some(p=>p.trim()))throw Error('The data bundle is truncated. Your previous data is still available.');
  await flush();
  for(const key of ['/api/meta','/api/badges','/material/index',...header.snapshots.map(d=>'/api/snapshot?date='+d)])if(!seen.has(key))throw Error('The bundle is missing required dashboard data.');
  const meta=JSON.parse((await stored('/api/meta',generation)).body);
  if(meta.snapshots.map(r=>r.date).join('|')!==header.snapshots.join('|'))throw Error('Bundle snapshot catalogue does not match its manifest.');
  // Keep metadata with its generation; the single active pointer is the commit boundary.
  const result={...header,count,added,reused,savedBytes:saved};
  await write('meta',generation,result);await write('meta','active',generation);
  // Cleanup cannot turn a successful commit into a reported failed import.
  try{await write('meta','pending',null);const retired=await read('meta','previous');await write('meta','previous',previous||null);if(retired&&retired!==previous)await removeGeneration(retired);await pruneContent([generation,previous]);}catch{}
  return result;
 }catch(error){await removeGeneration(generation).catch(()=>{});await write('meta','pending',null).catch(()=>{});throw error;}
}

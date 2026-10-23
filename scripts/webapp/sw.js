import {stored,recordResponse} from './assets/pwa-storage.mjs';
const BASE=new URL('./',self.location.href).pathname;
const PREFIX='mussim-shell-'+encodeURIComponent(BASE)+'-';
const CACHE=PREFIX+'__SHELL_VERSION__';
const FILES=['/','/index.html','/manifest.webmanifest','/icon.svg','/icon-192.png','/icon-512.png','/apple-touch-icon.png',...['workspace','match-centre','scenario-lab','performance-studio','competition-evidence','time-machine','forecast-lab','explore-visuals','pwa','pwa-storage','static-api'].map(n=>'/assets/'+n+'.mjs')].map(path=>BASE+path.slice(1));
self.addEventListener('install',event=>event.waitUntil((async()=>{const cache=await caches.open(CACHE);await cache.addAll(FILES);})()));
self.addEventListener('activate',event=>event.waitUntil((async()=>{for(const name of await caches.keys())if(name.startsWith(PREFIX)&&name!==CACHE)await caches.delete(name);await self.clients.claim();})()));
self.addEventListener('message',event=>{if(event.data?.type==='ACTIVATE')self.skipWaiting();});
self.addEventListener('fetch',event=>{const url=new URL(event.request.url);if(url.origin!==self.location.origin||!url.pathname.startsWith(BASE))return;const local='/'+url.pathname.slice(BASE.length);
 if(/^\/badges\/\d+\.png$/.test(local)){event.respondWith(stored(local).then(recordResponse));return;}
 if(local.startsWith('/api/')){event.respondWith(new Response(JSON.stringify({error:'Open MusSim and import a data bundle.'}),{status:404,headers:{'Content-Type':'application/json'}}));return;}
 if(event.request.mode==='navigate'){event.respondWith(caches.open(CACHE).then(c=>c.match(BASE+'index.html')));return;}
 if(FILES.includes(url.pathname))event.respondWith(caches.open(CACHE).then(async cache=>await cache.match(url.pathname)||fetch(event.request)));
});

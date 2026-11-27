/* iPad 電量監控站 Service Worker
 * 改版時要同時改這裡的 VERSION、version.json、index.html 的 ?v= 與 app.js 的 APP_VERSION。
 * 策略：網頁與程式「網路優先、斷線才用快取」；data.json、version.json 一律直接上網拿，不快取。
 * 新版 Service Worker 裝好後先等待，使用者按「立即更新」才接手（避免畫面用到一半被換掉）。
 */
const VERSION = '1.4.0';
const CACHE = `ipad-monitor-v${VERSION}`;
const SHELL = [
  './',
  'index.html',
  `style.css?v=${VERSION}`,
  `app.js?v=${VERSION}`,
  'icon.svg',
  'favicon-32.png',
  'manifest.webmanifest',
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('ipad-monitor-') && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  // 即時資料與版本檔：完全不經過快取
  if (/\/(data|version)\.json$/.test(url.pathname)) return;
  event.respondWith(
    fetch(req, { cache: 'no-cache' })
      .then((res) => {
        if (res.ok && res.type === 'basic') {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req).then((hit) => hit || (req.mode === 'navigate' ? caches.match('index.html') : Response.error()))),
  );
});

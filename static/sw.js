const CACHE_NAME = "salon-board-shell-v3";
const SHELL_URLS = [
  "/manifest.json",
  "/api/icon",
  "/static/js/master.js",
  "/static/css/master.css",
];
const SHELL_SET = new Set(SHELL_URLS);

self.addEventListener("install", function(event){
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(function(cache){return cache.addAll(SHELL_URLS);})
      .then(function(){return self.skipWaiting();})
  );
});

self.addEventListener("activate", function(event){
  event.waitUntil(
    caches.keys()
      .then(function(names){
        return Promise.all(names.map(function(name){
          if(name!==CACHE_NAME)return caches.delete(name);
          return Promise.resolve();
        }));
      })
      .then(function(){return self.clients.claim();})
  );
});

self.addEventListener("fetch", function(event){
  const url = new URL(event.request.url);
  const path = url.pathname;

  if(path.startsWith("/api/") && path!=="/api/icon")return;

  if(event.request.method==="GET" && SHELL_SET.has(path)){
    event.respondWith(
      caches.match(event.request).then(function(cached){
        return cached || fetch(event.request).then(function(response){
          const copy=response.clone();
          caches.open(CACHE_NAME).then(function(cache){cache.put(event.request,copy);});
          return response;
        });
      })
    );
  }
});

// Bump this when the shell JavaScript/CSS changes so installed PWAs fetch the
// current UI instead of retaining an older cached bundle.
const CACHE_NAME = "salon-board-shell-v24";
const SHELL_URLS = [
  "/master",
  "/manifest.json",
  "/api/icon",
  "/static/js/master.js",
  "/static/css/master.css",
];
const SHELL_SET = new Set(SHELL_URLS);

self.addEventListener("install", function(event){
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(function(cache){
        return Promise.all(SHELL_URLS.map(function(url){
          return fetch(new Request(url, {cache:"reload"})).then(function(response){
            if(!response.ok)throw new Error("Failed to cache "+url);
            return cache.put(url, response);
          });
        }));
      })
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

  // The schedule must be usable immediately after it has been opened once.
  // Serve its last successful response first, then refresh it in the
  // background. Requests explicitly marked no-store are the follow-up sync
  // made by the page and always use the network.
  if(event.request.method==="GET" && path.startsWith("/api/") && path!=="/api/icon"){
    event.respondWith(
      caches.open(CACHE_NAME).then(function(cache){
        if(event.request.cache==="no-store"){
          return fetch(event.request).then(function(response){
            if(response.ok)cache.put(event.request,response.clone());
            return response;
          });
        }
        return cache.match(event.request).then(function(cached){
          const refresh=fetch(event.request).then(function(response){
            if(response.ok)cache.put(event.request,response.clone());
            return response;
          });
          if(cached){event.waitUntil(refresh.catch(function(){}));return cached;}
          return refresh;
        });
      })
    );
    return;
  }

  if(event.request.mode==="navigate" && path==="/master"){
    event.respondWith(
      caches.open(CACHE_NAME).then(function(cache){
        return cache.match("/master").then(function(cached){
          const refresh=fetch(event.request).then(function(response){
            if(response.ok)cache.put("/master",response.clone());
            return response;
          });
          if(cached){event.waitUntil(refresh.catch(function(){}));return cached;}
          return refresh;
        });
      })
    );
    return;
  }

  if(event.request.method==="GET" && SHELL_SET.has(path)){
    event.respondWith(
      caches.match(event.request).then(function(cached){
        return cached || fetch(new Request(event.request, {cache:"reload"})).then(function(response){
          const copy=response.clone();
          caches.open(CACHE_NAME).then(function(cache){cache.put(event.request,copy);});
          return response;
        });
      })
    );
  }
});

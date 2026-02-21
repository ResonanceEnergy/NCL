// Super Agency Service Worker
// Enables offline functionality and caching

const CACHE_NAME = 'super-agency-v1';
const STATIC_CACHE = 'super-agency-static-v1';

// Files to cache for offline use
const STATIC_FILES = [
    '/',
    '/static/css/mobile.css',
    '/static/js/mobile.js',
    '/static/manifest.json',
    '/static/icon-192.png',
    '/static/icon-512.png'
];

// Install event - cache static files
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(STATIC_CACHE)
            .then(cache => {
                return cache.addAll(STATIC_FILES);
            })
            .then(() => {
                return self.skipWaiting();
            })
    );
});

// Activate event - clean up old caches
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.map(cacheName => {
                    if (cacheName !== STATIC_CACHE && cacheName !== CACHE_NAME) {
                        return caches.delete(cacheName);
                    }
                })
            );
        }).then(() => {
            return self.clients.claim();
        })
    );
});

// Fetch event - serve from cache when offline
self.addEventListener('fetch', event => {
    // Only handle GET requests
    if (event.request.method !== 'GET') return;

    // Skip cross-origin requests
    if (!event.request.url.startsWith(self.location.origin)) return;

    event.respondWith(
        caches.match(event.request)
            .then(response => {
                // Return cached version if available
                if (response) {
                    return response;
                }

                // Otherwise, fetch from network
                return fetch(event.request)
                    .then(response => {
                        // Don't cache API calls or non-success responses
                        if (event.request.url.includes('/api/') ||
                            !response.ok) {
                            return response;
                        }

                        // Cache successful responses
                        const responseClone = response.clone();
                        caches.open(CACHE_NAME)
                            .then(cache => {
                                cache.put(event.request, responseClone);
                            });

                        return response;
                    })
                    .catch(() => {
                        // Return offline fallback for HTML pages
                        if (event.request.headers.get('accept').includes('text/html')) {
                            return caches.match('/');
                        }
                    });
            })
    );
});

// Background sync for offline actions
self.addEventListener('sync', event => {
    if (event.tag === 'background-sync') {
        event.waitUntil(doBackgroundSync());
    }
});

function doBackgroundSync() {
    // Handle offline command execution
    return getPendingCommands()
        .then(commands => {
            return Promise.all(
                commands.map(command => executeCommand(command))
            );
        })
        .then(() => {
            return clearPendingCommands();
        });
}

function getPendingCommands() {
    // Get commands from IndexedDB or similar
    return Promise.resolve([]);
}

function executeCommand(command) {
    // Execute command when back online
    return fetch(`/api/command/${command.action}`, {
        method: 'POST',
        body: JSON.stringify(command.data),
        headers: {
            'Content-Type': 'application/json'
        }
    });
}

function clearPendingCommands() {
    // Clear executed commands
    return Promise.resolve();
}

// Push notifications (future enhancement)
self.addEventListener('push', event => {
    if (event.data) {
        const data = event.data.json();
        const options = {
            body: data.body,
            icon: '/static/icon-192.png',
            badge: '/static/icon-192.png',
            vibrate: [100, 50, 100],
            data: data.data
        };

        event.waitUntil(
            self.registration.showNotification(data.title, options)
        );
    }
});

// Notification click handler
self.addEventListener('notificationclick', event => {
    event.notification.close();

    event.waitUntil(
        clients.openWindow(event.notification.data.url || '/')
    );
});</content>
<parameter name="filePath">c:/Users/gripa/OneDrive - Grip and Ripp/Super Agency/Super-Agency/static/sw.js
/* Service worker for Web Push notifications (lifelog-picam). */
/* eslint-disable no-restricted-globals */

self.addEventListener('push', (event) => {
    let data = {};
    try {
        data = event.data ? event.data.json() : {};
    } catch (e) {
        data = { title: 'Lifelog', body: event.data ? event.data.text() : '' };
    }

    const title = data.title || 'Lifelog';
    const options = {
        body: data.body || '',
        icon: data.icon || '/logo192.png',
        badge: '/logo192.png',
        tag: data.tag || undefined,
        renotify: !!data.tag,
        vibrate: [200, 100, 200],
        data: { url: data.url || '/' },
    };

    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const url = (event.notification.data && event.notification.data.url) || '/';
    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
            for (const client of clients) {
                if ('focus' in client) {
                    client.focus();
                    if ('navigate' in client && url !== '/') client.navigate(url);
                    return undefined;
                }
            }
            if (self.clients.openWindow) return self.clients.openWindow(url);
            return undefined;
        }),
    );
});

/**
 * Web Push helpers: register the service worker, subscribe/unsubscribe the
 * browser, and report the subscription to the backend.
 */
import { getVapidPublicKey, subscribePush, unsubscribePush } from 'apis/notifications';

export const pushSupported = (): boolean =>
    'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;

const urlBase64ToUint8Array = (base64String: string): Uint8Array => {
    const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw = window.atob(base64);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
    return out;
};

const swUrl = (): string => `${process.env.PUBLIC_URL || ''}/sw.js`;
const swScope = (): string => `${process.env.PUBLIC_URL || ''}/`;

export const getPushPermission = (): NotificationPermission =>
    pushSupported() ? Notification.permission : 'denied';

export const isPushSubscribed = async (): Promise<boolean> => {
    if (!pushSupported()) return false;
    const reg = await navigator.serviceWorker.getRegistration(swScope());
    if (!reg) return false;
    const sub = await reg.pushManager.getSubscription();
    return !!sub;
};

/** Register SW, request permission, subscribe, and POST to backend. */
export const enablePush = async (device: string): Promise<boolean> => {
    if (!pushSupported()) throw new Error('Push not supported in this browser');

    const permission = await Notification.requestPermission();
    if (permission !== 'granted') return false;

    const reg = await navigator.serviceWorker.register(swUrl(), { scope: swScope() });
    await navigator.serviceWorker.ready;

    const { data } = await getVapidPublicKey();
    if (!data.enabled || !data.publicKey) throw new Error('Push not configured on server');

    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
        sub = await reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(data.publicKey),
        });
    }

    await subscribePush(device, sub.toJSON());
    return true;
};

export const disablePush = async (): Promise<void> => {
    if (!pushSupported()) return;
    const reg = await navigator.serviceWorker.getRegistration(swScope());
    if (!reg) return;
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
        await unsubscribePush(sub.endpoint).catch(() => undefined);
        await sub.unsubscribe();
    }
};

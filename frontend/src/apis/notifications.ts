import { api } from 'constants/urls';
import { Notification } from '@utils/types';

export const getNotifications = (device: string, unreadOnly = false, limit = 50) =>
    api.get<Notification[]>('/notify/notifications', {
        params: { device, unread_only: unreadOnly, limit },
    });

export const getUnreadCount = (device: string) =>
    api.get<{ count: number }>('/notify/notifications/unread-count', {
        params: { device },
    });

export const markRead = (device: string, ids: string[]) =>
    api.post('/notify/notifications/mark-read', { ids }, { params: { device } });

export const markAllRead = (device: string) =>
    api.post('/notify/notifications/mark-all-read', null, { params: { device } });

export const clearAll = (device: string) =>
    api.post('/notify/notifications/clear-all', null, { params: { device } });

export const deleteNotifications = (device: string, ids: string[]) =>
    api.post('/notify/notifications/delete', { ids }, { params: { device } });

// ── Web Push ────────────────────────────────────────────────────────────────

export const getVapidPublicKey = () =>
    api.get<{ publicKey: string; enabled: boolean }>('/notify/push/vapid-public-key');

export const subscribePush = (device: string, subscription: PushSubscriptionJSON) =>
    api.post('/notify/push/subscribe', subscription, { params: { device } });

export const unsubscribePush = (endpoint: string) =>
    api.post('/notify/push/unsubscribe', { endpoint });

export const sendTestPush = (device: string) =>
    api.post<{ ok: boolean; sent: number; reason?: string }>(
        '/notify/push/test',
        null,
        { params: { device } },
    );

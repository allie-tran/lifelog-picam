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

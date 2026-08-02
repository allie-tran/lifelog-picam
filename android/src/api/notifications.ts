import { axiosInstance } from '../constants';
import { Notification } from '../types';

export const getNotifications = (device: string, unreadOnly = false, limit = 50) =>
  axiosInstance.get<Notification[]>('/notify/notifications', {
    params: { device, unread_only: unreadOnly, limit },
  });

export const getUnreadCount = (device: string) =>
  axiosInstance.get<{ count: number }>('/notify/notifications/unread-count', {
    params: { device },
  });

export const markRead = (device: string, ids: string[]) =>
  axiosInstance.post('/notify/notifications/mark-read', { ids }, { params: { device } });

export const markAllRead = (device: string) =>
  axiosInstance.post('/notify/notifications/mark-all-read', null, { params: { device } });

export const clearAllNotifications = (device: string) =>
  axiosInstance.delete('/notify/notifications', { params: { device } });

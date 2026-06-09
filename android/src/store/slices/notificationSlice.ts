import { createAsyncThunk, createSlice, PayloadAction } from '@reduxjs/toolkit';
import { getNotifications, getUnreadCount, markAllRead, markRead } from '../../api/notifications';
import { Notification } from '../../types';

interface NotificationState {
  items: Notification[];
  unreadCount: number;
  loading: boolean;
  error: string | null;
}

const initialState: NotificationState = {
  items: [],
  unreadCount: 0,
  loading: false,
  error: null,
};

export const fetchNotifications = createAsyncThunk(
  'notifications/fetchAll',
  async ({ device, unreadOnly }: { device: string; unreadOnly?: boolean }) => {
    const res = await getNotifications(device, unreadOnly ?? false);
    return res.data;
  },
);

export const fetchUnreadCount = createAsyncThunk(
  'notifications/fetchUnreadCount',
  async (device: string) => {
    const res = await getUnreadCount(device);
    return res.data.count;
  },
);

export const markNotificationsRead = createAsyncThunk(
  'notifications/markRead',
  async ({ device, ids }: { device: string; ids: string[] }) => {
    await markRead(device, ids);
    return ids;
  },
);

export const markAllNotificationsRead = createAsyncThunk(
  'notifications/markAllRead',
  async (device: string) => {
    await markAllRead(device);
  },
);

const notificationSlice = createSlice({
  name: 'notifications',
  initialState,
  reducers: {},
  extraReducers: builder => {
    builder
      .addCase(fetchNotifications.pending, state => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchNotifications.fulfilled, (state, action: PayloadAction<Notification[]>) => {
        state.loading = false;
        state.items = action.payload;
        state.unreadCount = action.payload.filter(n => !n.read).length;
      })
      .addCase(fetchNotifications.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to load notifications';
      })
      .addCase(fetchUnreadCount.fulfilled, (state, action: PayloadAction<number>) => {
        state.unreadCount = action.payload;
      })
      .addCase(markNotificationsRead.fulfilled, (state, action: PayloadAction<string[]>) => {
        const ids = new Set(action.payload);
        state.items = state.items.map(n => ids.has(n.id) ? { ...n, read: true } : n);
        state.unreadCount = state.items.filter(n => !n.read).length;
      })
      .addCase(markAllNotificationsRead.fulfilled, state => {
        state.items = state.items.map(n => ({ ...n, read: true }));
        state.unreadCount = 0;
      });
  },
});

export default notificationSlice.reducer;

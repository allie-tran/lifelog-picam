import React, { useCallback, useEffect } from 'react';
import {
  ActivityIndicator,
  FlatList,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { COLORS } from '../constants';
import { useAppDispatch, useAppSelector } from '../store';
import {
  fetchNotifications,
  markAllNotificationsRead,
  markNotificationsRead,
} from '../store/slices/notificationSlice';
import { Notification } from '../types';

const TYPE_ICONS: Record<string, string> = {
  new_location: '📍',
  unusual_activity: '✨',
  day_complete: '📋',
  novelty: '🌟',
};

const NotificationItem = ({
  item,
  onPress,
}: {
  item: Notification;
  onPress: (id: string) => void;
}) => (
  <TouchableOpacity
    style={[styles.card, item.read && styles.cardRead]}
    onPress={() => !item.read && onPress(item.id)}
    activeOpacity={0.7}
  >
    <View style={styles.cardRow}>
      <Text style={styles.typeIcon}>{TYPE_ICONS[item.type] ?? '🔔'}</Text>
      <View style={styles.cardContent}>
        <Text style={[styles.title, item.read && styles.titleRead]} numberOfLines={1}>
          {item.title}
        </Text>
        {item.body ? (
          <Text style={styles.body} numberOfLines={2}>
            {item.body}
          </Text>
        ) : null}
        <Text style={styles.date}>{item.date}</Text>
      </View>
      {!item.read && <View style={styles.unreadDot} />}
    </View>
  </TouchableOpacity>
);

const NotificationsScreen = () => {
  const dispatch = useAppDispatch();
  const device = useAppSelector(s => s.auth.deviceId ?? s.auth.devices?.[0] ?? '');
  const { items, loading, unreadCount } = useAppSelector(s => s.notifications);

  const load = useCallback(() => {
    if (device) dispatch(fetchNotifications({ device }));
  }, [dispatch, device]);

  useEffect(() => {
    load();
  }, [load]);

  const handleMarkRead = useCallback(
    (id: string) => {
      dispatch(markNotificationsRead({ device, ids: [id] }));
    },
    [dispatch, device],
  );

  const handleMarkAll = useCallback(() => {
    dispatch(markAllNotificationsRead(device));
  }, [dispatch, device]);

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>
          Notifications{unreadCount > 0 ? `  (${unreadCount} new)` : ''}
        </Text>
        {unreadCount > 0 && (
          <TouchableOpacity onPress={handleMarkAll} style={styles.markAllBtn}>
            <Text style={styles.markAllText}>Mark all read</Text>
          </TouchableOpacity>
        )}
      </View>

      {loading && items.length === 0 ? (
        <ActivityIndicator style={styles.spinner} color={COLORS.primary} />
      ) : items.length === 0 ? (
        <View style={styles.emptyWrap}>
          <Text style={styles.emptyIcon}>🔕</Text>
          <Text style={styles.emptyText}>No notifications yet</Text>
        </View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={n => n.id}
          renderItem={({ item }) => (
            <NotificationItem item={item} onPress={handleMarkRead} />
          )}
          onRefresh={load}
          refreshing={loading}
          contentContainerStyle={styles.list}
        />
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.background },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: COLORS.surface,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.divider,
  },
  headerTitle: { fontSize: 16, fontWeight: '700', color: COLORS.textPrimary },
  markAllBtn: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    backgroundColor: COLORS.primary + '22',
    borderRadius: 8,
  },
  markAllText: { fontSize: 13, color: COLORS.primary, fontWeight: '600' },
  list: { padding: 12 },
  card: {
    backgroundColor: COLORS.surface,
    borderRadius: 10,
    marginBottom: 8,
    padding: 12,
    borderLeftWidth: 3,
    borderLeftColor: COLORS.primary,
    elevation: 1,
  },
  cardRead: { borderLeftColor: COLORS.divider, opacity: 0.7 },
  cardRow: { flexDirection: 'row', alignItems: 'flex-start' },
  typeIcon: { fontSize: 20, marginRight: 10, marginTop: 2 },
  cardContent: { flex: 1 },
  title: { fontSize: 14, fontWeight: '700', color: COLORS.textPrimary, marginBottom: 3 },
  titleRead: { fontWeight: '400' },
  body: { fontSize: 13, color: COLORS.textSecondary, lineHeight: 18, marginBottom: 4 },
  date: { fontSize: 11, color: COLORS.textSecondary },
  unreadDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: COLORS.primary,
    marginLeft: 8,
    marginTop: 4,
  },
  spinner: { marginTop: 40 },
  emptyWrap: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  emptyIcon: { fontSize: 48, marginBottom: 12 },
  emptyText: { color: COLORS.textSecondary, fontSize: 15 },
});

export default NotificationsScreen;

import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import dayjs from 'dayjs';
import { getAllDates, getDaySummary, getImagesByHour, processDate } from '../api/browsing';
import ImageCard from '../components/ImageCard';
import { useAppSelector } from '../store';
import { COLORS } from '../constants';
import { DaySummary, ImageObject, RootStackParamList } from '../types';

// ── Category colors (subset matching web app) ────────────────────────────────
const CAT_COLORS: Record<string, string> = {
  Coding: '#C8E9A0', Writing: '#C8E9A0', 'Email & Admin': '#C8E9A0',
  Meeting: '#50FA7B', 'Zoom Call': '#50FA7B',
  Lecturing: '#FFB86C', 'Lab / Tutorial': '#FFB86C',
  Commuting: '#6DD3CE', Walking: '#6DD3CE', Travelling: '#6DD3CE',
  Eating: '#FF9E7D', Cooking: '#FF9E7D',
  Exercise: '#FF79C6', Sport: '#FF79C6',
  Reading: '#BD93F9', Sleeping: '#6272A4',
};
const catColor = (name: string) => CAT_COLORS[name] ?? COLORS.divider;

// ── Day summary card ──────────────────────────────────────────────────────────
const DaySummaryCard = ({ summary }: { summary: DaySummary }) => {
  const [expanded, setExpanded] = useState(false);

  const topCategories = Object.entries(summary.categoryMinutes ?? {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 6);

  return (
    <View style={ss.card}>
      <TouchableOpacity style={ss.cardHeader} onPress={() => setExpanded(v => !v)} activeOpacity={0.7}>
        <Text style={ss.cardTitle}>📋 Day Summary</Text>
        <Text style={ss.cardToggle}>{expanded ? '▲' : '▼'}</Text>
      </TouchableOpacity>

      {/* Category minute badges — always visible */}
      {topCategories.length > 0 && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={ss.catRow}
          contentContainerStyle={ss.catRowContent}>
          {topCategories.map(([name, mins]) => (
            <View key={name} style={[ss.catBadge, { backgroundColor: catColor(name) }]}>
              <Text style={ss.catName}>{name}</Text>
              <Text style={ss.catMins}>{Math.round(mins)}m</Text>
            </View>
          ))}
        </ScrollView>
      )}

      {expanded && (
        <>
          {/* Summary text */}
          {!!summary.summaryText && (
            <Text style={ss.summaryText}>{summary.summaryText}</Text>
          )}

          {/* Segment timeline */}
          {summary.segments?.length > 0 && (
            <View style={ss.segments}>
              {summary.segments.map((seg, i) => (
                <View key={i} style={ss.segRow}>
                  <View style={[ss.segDot, { backgroundColor: catColor(seg.activity) }]} />
                  <Text style={ss.segTime}>
                    {dayjs(seg.startTime).format('HH:mm')}–{dayjs(seg.endTime).format('HH:mm')}
                  </Text>
                  <Text style={ss.segActivity} numberOfLines={1}>{seg.activity}</Text>
                </View>
              ))}
            </View>
          )}
        </>
      )}
    </View>
  );
};

// ── Main screen ───────────────────────────────────────────────────────────────
const BrowseScreen = () => {
  const deviceId = useAppSelector(s => s.auth.deviceId);
  const navigation = useNavigation<NativeStackNavigationProp<RootStackParamList>>();
  const [dates, setDates] = useState<string[]>([]);
  const [selectedDate, setSelectedDate] = useState<string>(dayjs().format('YYYY-MM-DD'));
  const [availableHours, setAvailableHours] = useState<number[]>([]);
  const [selectedHour, setSelectedHour] = useState<number>(0);
  const [images, setImages] = useState<ImageObject[]>([]);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [summary, setSummary] = useState<DaySummary | null>(null);
  const [processing, setProcessing] = useState(false);

  useEffect(() => {
    if (!deviceId) { return; }
    getAllDates(deviceId)
      .then(res => {
        const d = res.data as string[];
        setDates(d);
        if (d.length > 0) { setSelectedDate(d[0]); }
      })
      .catch(() => {});
  }, [deviceId]);

  // Fetch day summary whenever date changes
  useEffect(() => {
    if (!deviceId || !selectedDate) { return; }
    setSummary(null);
    getDaySummary(deviceId, selectedDate)
      .then(res => setSummary(res.data))
      .catch(() => {});
  }, [deviceId, selectedDate]);

  const loadImages = useCallback(async (date: string, hour: number, pg: number) => {
    if (!deviceId) { return; }
    setLoading(true);
    try {
      const res = await getImagesByHour(deviceId, date, hour, pg);
      const { images: imgs, available_hours, total_pages } = res.data as any;
      setImages(pg === 1 ? imgs : (prev: ImageObject[]) => [...prev, ...imgs]);
      setAvailableHours(available_hours ?? []);
      setTotalPages(total_pages ?? 1);
      if (pg === 1 && available_hours?.length > 0) {
        setSelectedHour(available_hours[0]);
      }
    } catch {}
    finally { setLoading(false); }
  }, [deviceId]);

  useEffect(() => {
    setPage(1);
    loadImages(selectedDate, selectedHour, 1);
  }, [selectedDate, selectedHour, deviceId]);

  const loadMore = () => {
    if (page < totalPages && !loading) {
      const next = page + 1;
      setPage(next);
      loadImages(selectedDate, selectedHour, next);
    }
  };

  const ListHeader = (
    <>
      {/* Hour strip */}
      {availableHours.length > 0 && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false}
          style={styles.hourStrip} contentContainerStyle={styles.dateStripContent}>
          {availableHours.map(h => (
            <TouchableOpacity
              key={h}
              style={[styles.hourChip, selectedHour === h && styles.hourChipActive]}
              onPress={() => { setSelectedHour(h); setPage(1); }}
            >
              <Text style={[styles.hourChipText, selectedHour === h && styles.hourChipTextActive]}>
                {String(h).padStart(2, '0')}:00
              </Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      )}

      {/* Day header */}
      <View style={styles.header}>
        <Text style={styles.headerDate}>{dayjs(selectedDate).format('dddd, D MMMM YYYY')}</Text>
        <View style={styles.headerRight}>
          <Text style={styles.headerCount}>{images.length} photos</Text>
          <TouchableOpacity
            style={styles.mapBtn}
            onPress={() => navigation.navigate('LocationMap', { date: selectedDate })}
          >
            <Text style={styles.mapBtnText}>📍</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.reprocessBtn, processing && styles.reprocessBtnDisabled]}
            disabled={processing}
            onPress={() => {
              Alert.alert('Re-process Day', 'Choose what to re-run for this date:', [
                { text: 'Cancel', style: 'cancel' },
                {
                  text: 'Re-segment', onPress: async () => {
                    setProcessing(true);
                    await processDate(deviceId, selectedDate, true, false).catch(() => {});
                    setSummary(null);
                    setProcessing(false);
                  },
                },
                {
                  text: 'Re-annotate', onPress: async () => {
                    setProcessing(true);
                    await processDate(deviceId, selectedDate, false, true).catch(() => {});
                    getDaySummary(deviceId, selectedDate).then(r => setSummary(r.data)).catch(() => {});
                    setProcessing(false);
                  },
                },
                {
                  text: 'Both', onPress: async () => {
                    setProcessing(true);
                    await processDate(deviceId, selectedDate, true, true).catch(() => {});
                    getDaySummary(deviceId, selectedDate).then(r => setSummary(r.data)).catch(() => {});
                    setProcessing(false);
                  },
                },
              ]);
            }}
          >
            {processing
              ? <ActivityIndicator size="small" color={COLORS.primary} />
              : <Text style={styles.reprocessBtnText}>⟳</Text>}
          </TouchableOpacity>
        </View>
      </View>

      {/* Day summary */}
      {summary && <DaySummaryCard summary={summary} />}
    </>
  );

  return (
    <View style={styles.container}>
      {/* Date strip */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false}
        style={styles.dateStrip} contentContainerStyle={styles.dateStripContent}>
        {dates.map(d => (
          <TouchableOpacity
            key={d}
            style={[styles.dateChip, selectedDate === d && styles.dateChipActive]}
            onPress={() => { setSelectedDate(d); setPage(1); }}
          >
            <Text style={[styles.dateChipText, selectedDate === d && styles.dateChipTextActive]}>
              {dayjs(d).format('D MMM')}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {loading && images.length === 0 ? (
        <ActivityIndicator style={styles.loader} color={COLORS.primary} size="large" />
      ) : (
        <FlatList
          data={images}
          keyExtractor={item => item.imagePath}
          numColumns={3}
          contentContainerStyle={styles.grid}
          ListHeaderComponent={ListHeader}
          renderItem={({ item }) => (
            <ImageCard image={item} deviceId={deviceId} size={114} />
          )}
          onEndReached={loadMore}
          onEndReachedThreshold={0.3}
          ListFooterComponent={
            loading ? <ActivityIndicator color={COLORS.primary} style={{ marginVertical: 12 }} /> : null
          }
          ListEmptyComponent={
            <View style={styles.empty}>
              <Text style={styles.emptyText}>No images for this hour</Text>
            </View>
          }
        />
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.background },
  dateStrip: { maxHeight: 46, backgroundColor: COLORS.surface, borderBottomWidth: 1, borderColor: COLORS.divider },
  dateStripContent: { paddingHorizontal: 8, paddingVertical: 8, gap: 6 },
  dateChip: {
    paddingHorizontal: 12, paddingVertical: 4, borderRadius: 20,
    borderWidth: 1, borderColor: COLORS.divider, backgroundColor: COLORS.background,
  },
  dateChipActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  dateChipText: { fontSize: 12, color: COLORS.textSecondary },
  dateChipTextActive: { color: '#fff', fontWeight: '600' },
  hourStrip: { maxHeight: 40, backgroundColor: COLORS.surface },
  hourChip: {
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: 12,
    marginHorizontal: 3, backgroundColor: COLORS.background, borderWidth: 1, borderColor: COLORS.divider,
  },
  hourChipActive: { backgroundColor: COLORS.secondary, borderColor: COLORS.secondary },
  hourChipText: { fontSize: 11, color: COLORS.textSecondary },
  hourChipTextActive: { color: '#fff', fontWeight: '600' },
  header: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    paddingHorizontal: 14, paddingVertical: 8,
  },
  headerDate: { fontSize: 13, fontWeight: '600', color: COLORS.textPrimary, flex: 1 },
  headerRight: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  headerCount: { fontSize: 12, color: COLORS.textSecondary },
  mapBtn: {
    width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center',
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.divider,
  },
  mapBtnText: { fontSize: 14 },
  reprocessBtn: {
    width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center',
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.divider,
  },
  reprocessBtnDisabled: { opacity: 0.4 },
  reprocessBtnText: { fontSize: 16, color: COLORS.primary },
  grid: { paddingHorizontal: 4, paddingBottom: 16 },
  loader: { flex: 1, marginTop: 60 },
  empty: { padding: 40, alignItems: 'center' },
  emptyText: { color: COLORS.textSecondary, fontSize: 14 },
});

// Day summary card styles
const ss = StyleSheet.create({
  card: {
    marginHorizontal: 10, marginBottom: 10, borderRadius: 14,
    backgroundColor: COLORS.surface, elevation: 2, overflow: 'hidden',
  },
  cardHeader: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    paddingHorizontal: 14, paddingVertical: 10,
  },
  cardTitle: { fontSize: 13, fontWeight: '700', color: COLORS.textPrimary },
  cardToggle: { fontSize: 12, color: COLORS.textSecondary },
  catRow: { maxHeight: 36 },
  catRowContent: { paddingHorizontal: 12, paddingBottom: 8, gap: 6 },
  catBadge: {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    paddingHorizontal: 10, paddingVertical: 3, borderRadius: 12,
  },
  catName: { fontSize: 11, fontWeight: '600', color: '#333' },
  catMins: { fontSize: 10, color: '#555' },
  summaryText: {
    fontSize: 13, color: COLORS.textPrimary, lineHeight: 19,
    paddingHorizontal: 14, paddingTop: 6, paddingBottom: 10,
  },
  segments: { paddingHorizontal: 14, paddingBottom: 12, gap: 6 },
  segRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  segDot: { width: 8, height: 8, borderRadius: 4 },
  segTime: { fontSize: 11, color: COLORS.textSecondary, width: 90 },
  segActivity: { fontSize: 12, color: COLORS.textPrimary, flex: 1 },
});

export default BrowseScreen;

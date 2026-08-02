import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Image,
  Modal,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  TouchableWithoutFeedback,
  View,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';
import relativeTime from 'dayjs/plugin/relativeTime';

dayjs.extend(utc);
dayjs.extend(timezone);
dayjs.extend(relativeTime);
import { getAllDates, getCurrentStatus, getDaySummary, getImagesByHour, processDate } from '../api/browsing';
import ImageCard from '../components/ImageCard';
import { useAppSelector } from '../store';
import { COLORS, config, formatTimeTz } from '../constants';
import { BrowseSegment, CurrentStatus, DaySummary, RootStackParamList } from '../types';
import useSWRNative from '@nandorojo/swr-react-native'

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

const GROUP_COLORS: Record<string, string> = {
  'Work – Research & Writing': '#C8E9A0',
  'Meetings & Collaboration': '#50FA7B',
  'Teaching & Outreach': '#FFB86C',
  'Travel': '#6DD3CE',
  'Food & Drink': '#FF5555',
  'Leisure & Wellbeing': '#8BE9FD',
  'Social & Personal': '#BD93F9',
  'Sleep / Downtime': '#2c3e50',
  'Miscellaneous': '#E1E7E7',
};

const CONFIDENCE_COLORS: Record<string, string> = {
  High: COLORS.success,
  Medium: '#FFB86C',
  Low: COLORS.error,
};

const SENSOR_LABELS: Record<string, string> = {
  camera: 'Camera', location: 'GPS', heart_rate: 'Heart',
  accelerometer: 'Motion', ppg: 'PPG',
};

// ── Current status card ───────────────────────────────────────────────────────
const CurrentStatusCard = ({ status, deviceId }: { status: CurrentStatus; deviceId: string }) => {
  const thumbnailUri = status.currentThumbnail
    ? `${config.imageUrl}/${deviceId}/${status.currentThumbnail}`
    : null;

  const lastSeenText = status.cameraLastSeen
    ? dayjs.utc(status.cameraLastSeen).fromNow()
    : 'never';

  const sinceText = status.segmentSince
    ? dayjs.utc(status.segmentSince).fromNow()
    : null;

  const loc = status.currentLocation;
  const locLabel = loc
    ? (loc.name && loc.name !== loc.city ? loc.name : null) ?? loc.suburb ?? loc.city ?? 'Unknown location'
    : null;
  const locSub = loc?.city && loc.name !== loc.city ? loc.city : null;
  const isMoving = loc?.stop === false;

  return (
    <View style={cs.card}>
      {/* Header */}
      <View style={cs.header}>
        <View style={cs.headerLeft}>
          <View style={[cs.dot, { backgroundColor: status.cameraOnline ? '#2ecc71' : COLORS.divider }]} />
          <Text style={cs.title}>Current Status</Text>
          {status.cameraOnline
            ? <View style={cs.liveChip}><Text style={cs.liveChipText}>Live</Text></View>
            : <Text style={cs.offlineText}>Last seen {lastSeenText}</Text>
          }
        </View>
        {/* Sensor dots */}
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={cs.sensorRow} contentContainerStyle={cs.sensorRowContent}>
          {status.sensors.map(s => (
            <View key={`${s.deviceId}-${s.sensorType}`} style={cs.sensorItem}>
              <View style={[cs.dot, { backgroundColor: s.online ? '#2ecc71' : COLORS.divider }]} />
              <Text style={cs.sensorLabel}>{s.nickname || SENSOR_LABELS[s.sensorType] || s.sensorType}</Text>
            </View>
          ))}
        </ScrollView>
      </View>

      <View style={cs.divider} />

      {/* Body */}
      <View style={cs.body}>
        {thumbnailUri && (
          <Image source={{ uri: thumbnailUri }} style={cs.thumbnail} resizeMode="cover" />
        )}
        <View style={cs.bodyText}>
          {status.currentActivity && (
            <Text style={cs.activityText}>{status.currentActivity}</Text>
          )}
          {status.currentActivityDescription && (
            <Text style={cs.activityDesc} numberOfLines={2}>{status.currentActivityDescription}</Text>
          )}
          {locLabel && (
            <Text style={cs.locationText}>
              {isMoving ? '🚶 ' : '📍 '}{locLabel}{locSub ? `, ${locSub}` : ''}
            </Text>
          )}
          {sinceText && (
            <Text style={cs.sinceText}>⏱ Since {sinceText}</Text>
          )}
        </View>
      </View>

      {status.summary && (
        <>
          <View style={cs.divider} />
          <Text style={cs.summaryText}>{status.summary}</Text>
        </>
      )}
    </View>
  );
};

// ── Calendar picker modal ─────────────────────────────────────────────────────
const DAYS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];

const CalendarPicker = ({
  visible,
  availableDates,
  selectedDate,
  onSelect,
  onClose,
}: {
  visible: boolean;
  availableDates: string[];
  selectedDate: string;
  onSelect: (d: string) => void;
  onClose: () => void;
}) => {
  const availableSet = useMemo(() => new Set(availableDates), [availableDates]);
  const [cursor, setCursor] = useState(() => dayjs(selectedDate).startOf('month'));

  useEffect(() => {
    if (visible) setCursor(dayjs(selectedDate).startOf('month'));
  }, [visible, selectedDate]);

  const firstDay = cursor.day();
  const daysInMonth = cursor.daysInMonth();

  const cells: (number | null)[] = [
    ...Array(firstDay).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];
  while (cells.length % 7 !== 0) cells.push(null);

  const hasPrev = availableDates.some(d => d < cursor.format('YYYY-MM'));
  const hasNext = availableDates.some(d => d >= cursor.add(1, 'month').format('YYYY-MM'));

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <TouchableWithoutFeedback onPress={onClose}>
        <View style={cal.overlay}>
          <TouchableWithoutFeedback>
            <View style={cal.sheet}>
              <View style={cal.header}>
                <TouchableOpacity onPress={() => setCursor(c => c.subtract(1, 'month'))} disabled={!hasPrev} style={cal.navBtn}>
                  <Text style={[cal.navText, !hasPrev && cal.navDisabled]}>‹</Text>
                </TouchableOpacity>
                <Text style={cal.monthLabel}>{cursor.format('MMMM YYYY')}</Text>
                <TouchableOpacity onPress={() => setCursor(c => c.add(1, 'month'))} disabled={!hasNext} style={cal.navBtn}>
                  <Text style={[cal.navText, !hasNext && cal.navDisabled]}>›</Text>
                </TouchableOpacity>
              </View>
              <View style={cal.weekRow}>
                {DAYS.map(d => (
                  <Text key={d} style={cal.weekDay}>{d}</Text>
                ))}
              </View>
              {Array.from({ length: cells.length / 7 }, (_, week) => (
                <View key={week} style={cal.weekRow}>
                  {cells.slice(week * 7, week * 7 + 7).map((day, col) => {
                    if (!day) return <View key={col} style={cal.cell} />;
                    const iso = cursor.date(day).format('YYYY-MM-DD');
                    const available = availableSet.has(iso);
                    const selected = iso === selectedDate;
                    return (
                      <TouchableOpacity
                        key={col}
                        style={[cal.cell, selected && cal.cellSelected, available && !selected && cal.cellAvailable]}
                        onPress={() => { if (available) { onSelect(iso); onClose(); } }}
                        disabled={!available}
                        activeOpacity={0.7}
                      >
                        <Text style={[cal.cellText, selected && cal.cellTextSelected, !available && cal.cellTextDisabled]}>
                          {day}
                        </Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>
              ))}
            </View>
          </TouchableWithoutFeedback>
        </View>
      </TouchableWithoutFeedback>
    </Modal>
  );
};

// ── Day summary card ──────────────────────────────────────────────────────────
const minutesToHM = (m: number): string => {
  const total = Math.round(m);
  const h = Math.floor(total / 60);
  const mm = total % 60;
  if (h === 0) return `${mm}m`;
  if (mm === 0) return `${h}h`;
  return `${h}h ${mm}m`;
};

const DaySummaryCard = ({ summary, deviceId }: { summary: DaySummary; deviceId: string }) => {
  const [expanded, setExpanded] = useState(false);
  const [periodIndex, setPeriodIndex] = useState(0);
  const [segmentIndex, setSegmentIndex] = useState(0);

  const topCategories = Object.entries(summary.categoryMinutes ?? {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 6);

  const totalMinutes = summary.totalMinutes ??
    (summary.segments?.reduce((sum, s) => sum + s.duration / 60, 0) ?? 0);

  const periodNames = Object.keys(summary.periodMetrics ?? {});
  const currentPeriodName = periodNames[periodIndex] ?? '';
  const currentPeriodSegs = summary.periodMetrics?.[currentPeriodName] ?? [];
  const currentSeg = currentPeriodSegs[segmentIndex];
  const summaryLines = (summary.customSummaries?.[currentPeriodName] ?? '')
    .split('\n').filter(l => l.trim());

  return (
    <View style={ss.card}>
      {/* Header */}
      <TouchableOpacity style={ss.cardHeader} onPress={() => setExpanded(v => !v)} activeOpacity={0.7}>
        <Text style={ss.cardTitle}>📋 Day Summary</Text>
        <Text style={ss.cardToggle}>{expanded ? '▲' : '▼'}</Text>
      </TouchableOpacity>

      {/* Category badges — always visible */}
      {topCategories.length > 0 && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={ss.catRow} contentContainerStyle={ss.catRowContent}>
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
          {/* Overview stats */}
          <View style={ss.overviewRow}>
            <View style={ss.overviewStat}>
              <Text style={ss.overviewValue}>{minutesToHM(totalMinutes)}</Text>
              <Text style={ss.overviewLabel}>Captured</Text>
            </View>
            <View style={ss.overviewDivider} />
            <View style={ss.overviewStat}>
              <Text style={ss.overviewValue}>{summary.totalImages}</Text>
              <Text style={ss.overviewLabel}>Images</Text>
            </View>
          </View>

          {/* Narrative summary */}
          {!!summary.summaryText && (
            <View style={ss.section}>
              <Text style={ss.sectionLabel}>Day Overview</Text>
              <Text style={ss.summaryText}>{summary.summaryText}</Text>
            </View>
          )}

          {/* Timeline bar */}
          {summary.segments?.length > 0 && (
            <View style={ss.section}>
              <Text style={ss.sectionLabel}>Timeline</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                <View style={ss.timelineBar}>
                  {summary.segments.map((seg, i) => (
                    <View
                      key={i}
                      style={[ss.timelineSegment, {
                        width: Math.max(4, seg.duration / 180),
                        backgroundColor: catColor(seg.activity),
                      }]}
                    />
                  ))}
                </View>
              </ScrollView>
            </View>
          )}

          {/* Binary metrics — progress bars */}
          {Object.keys(summary.binaryMetrics ?? {}).length > 0 && (
            <View style={ss.section}>
              <Text style={ss.sectionLabel}>State Distribution</Text>
              {Object.entries(summary.binaryMetrics).map(([name, count]) => {
                const pct = summary.totalImages > 0 ? (count / summary.totalImages) * 100 : 0;
                return (
                  <View key={name} style={ss.barRow}>
                    <View style={ss.barLabelRow}>
                      <Text style={ss.barName}>{name}</Text>
                      <Text style={ss.barPct}>{pct.toFixed(0)}%</Text>
                    </View>
                    <View style={ss.barTrack}>
                      <View style={[ss.barFill, { width: `${pct}%` as any }]} />
                    </View>
                  </View>
                );
              })}
            </View>
          )}

          {/* Burst metrics — count badges */}
          {Object.keys(summary.burstMetrics ?? {}).length > 0 && (
            <View style={ss.section}>
              <Text style={ss.sectionLabel}>Daily Bursts</Text>
              <View style={ss.burstGrid}>
                {Object.entries(summary.burstMetrics).map(([name, timestamps]) => (
                  <View key={name} style={ss.burstCell}>
                    <Text style={ss.burstCount}>{timestamps.length}</Text>
                    <Text style={ss.burstName}>{name}</Text>
                  </View>
                ))}
              </View>
            </View>
          )}

          {/* Activity categories — horizontal bars */}
          {Object.keys(summary.categoryMinutes ?? {}).length > 0 && (
            <View style={ss.section}>
              <Text style={ss.sectionLabel}>Activity Categories</Text>
              {Object.entries(summary.categoryMinutes)
                .sort(([, a], [, b]) => b - a)
                .map(([name, mins]) => {
                  const pct = totalMinutes > 0 ? (mins / totalMinutes) * 100 : 0;
                  return (
                    <View key={name} style={ss.barRow}>
                      <View style={ss.barLabelRow}>
                        <View style={[ss.catDot, { backgroundColor: catColor(name) }]} />
                        <Text style={ss.barName}>{name}</Text>
                        <Text style={ss.barPct}>{minutesToHM(mins)}</Text>
                      </View>
                      <View style={ss.barTrack}>
                        <View style={[ss.barFill, { width: `${pct}%` as any, backgroundColor: catColor(name) }]} />
                      </View>
                    </View>
                  );
                })}
            </View>
          )}

          {/* Period metrics — tabs + image carousel */}
          {periodNames.length > 0 && (
            <View style={[ss.section, { paddingBottom: 0 }]}>
              <Text style={ss.sectionLabel}>Activity Periods</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={ss.periodTabsRow}>
                {periodNames.map((name, i) => (
                  <TouchableOpacity
                    key={name}
                    style={[ss.periodTab, { backgroundColor: catColor(name) + (periodIndex === i ? 'FF' : '44') }]}
                    onPress={() => { setPeriodIndex(i); setSegmentIndex(0); }}
                  >
                    <Text style={[ss.periodTabText, periodIndex === i && ss.periodTabTextActive]}>{name}</Text>
                  </TouchableOpacity>
                ))}
              </ScrollView>

              {currentPeriodSegs.length > 0 && (
                <View style={ss.periodCard}>
                  {/* Occurrence time tabs */}
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={ss.occurrenceRow}>
                    {currentPeriodSegs.map((seg, i) => (
                      <TouchableOpacity
                        key={i}
                        style={[ss.occurrenceTab, segmentIndex === i && ss.occurrenceTabActive]}
                        onPress={() => setSegmentIndex(i)}
                      >
                        <Text style={[ss.occurrenceTabText, segmentIndex === i && ss.occurrenceTabTextActive]}>
                          {formatTimeTz(seg.startTime, seg.representativeImage?.timezone || config.defaultTimezone)}
                        </Text>
                      </TouchableOpacity>
                    ))}
                  </ScrollView>

                  {summaryLines[segmentIndex] ? (
                    <Text style={ss.periodSummary}>{summaryLines[segmentIndex]}</Text>
                  ) : null}

                  {(currentSeg?.representativeImages?.length ?? 0) > 0 && (
                    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={ss.periodImages}>
                      {currentSeg.representativeImages.map((img, i) => {
                        const uri = img.thumbnail ? `${config.imageUrl}/${deviceId}/${img.thumbnail}` : null;
                        return uri ? (
                          <View key={i} style={ss.periodImageWrap}>
                            <Image source={{ uri }} style={ss.periodImage} resizeMode="cover" />
                            <Text style={ss.periodImageTime}>{formatTimeTz(img.timestamp, img.timezone || config.defaultTimezone)}</Text>
                          </View>
                        ) : null;
                      })}
                    </ScrollView>
                  )}
                </View>
              )}
            </View>
          )}

        </>
      )}
    </View>
  );
};

// ── Segment block ─────────────────────────────────────────────────────────────
const BORING_NAMES = new Set(['---', 'Unknown Place', 'Unknown', '']);

const SegmentBlock = ({ segment, deviceId, index }: { segment: BrowseSegment; deviceId: string; index: number }) => {
  const firstImage = segment.images[0];
  const lastImage = segment.images[segment.images.length - 1];
  const tz = firstImage?.timezone || config.defaultTimezone;

  const startTime = firstImage?.timestamp ? formatTimeTz(firstImage.timestamp, tz) : null;
  const endTime = lastImage?.timestamp ? formatTimeTz(lastImage.timestamp, tz) : null;

  const durationMs = firstImage?.timestamp && lastImage?.timestamp
    ? new Date(lastImage.timestamp.endsWith('Z') ? lastImage.timestamp : lastImage.timestamp + 'Z').getTime()
      - new Date(firstImage.timestamp.endsWith('Z') ? firstImage.timestamp : firstImage.timestamp + 'Z').getTime()
    : 0;
  const durationMins = Math.round(durationMs / 60000);
  const durationText = durationMins < 1 ? '<1 min'
    : durationMins < 60 ? `${durationMins} min`
    : `${Math.floor(durationMins / 60)}h ${durationMins % 60}m`;

  const loc = segment.location;
  const isMove = loc?.stop === false;
  const locName = loc?.name && !BORING_NAMES.has(loc.name) ? loc.name : null;
  const locLine1 = locName ?? loc?.suburb ?? loc?.city ?? null;
  const locLine2 = [loc?.suburb !== locLine1 ? loc?.suburb : null, loc?.city !== locLine1 ? loc?.city : null, loc?.country]
    .filter(Boolean).join(', ') || null;

  const activity = firstImage?.activity;
  const group = firstImage?.activityGroup;
  const confidence = firstImage?.activityConfidence;
  const description = firstImage?.activityDescription;

  return (
    <View style={sg.block}>
      {/* Location row */}
      {locLine1 && (
        <View style={sg.locationRow}>
          <Text style={sg.locationIcon}>{isMove ? '🚶' : '📍'}</Text>
          <View style={sg.locationText}>
            <Text style={sg.locationName}>{locLine1}</Text>
            {locLine2 ? <Text style={sg.locationSub}>{locLine2}</Text> : null}
          </View>
        </View>
      )}

      <View style={sg.infoRow}>
        {/* Activity + meta */}
        <View style={sg.infoLeft}>
          <View style={sg.activityRow}>
            <Text style={sg.activity}>{activity || 'No Activity'}</Text>
            {group && (
              <View style={[sg.groupChip, { backgroundColor: GROUP_COLORS[group] ?? COLORS.divider }]}>
                <Text style={sg.groupChipText}>{group}</Text>
              </View>
            )}
            {confidence && (
              <Text style={[sg.confidence, { color: CONFIDENCE_COLORS[confidence] ?? COLORS.textSecondary }]}>
                {confidence}
              </Text>
            )}
          </View>
          <Text style={sg.meta}>
            {durationText} · {segment.images.length} image{segment.images.length !== 1 ? 's' : ''}
          </Text>
          {description ? <Text style={sg.description} numberOfLines={3}>{description}</Text> : null}
        </View>

        {/* Timestamp */}
        <View style={sg.timeCol}>
          {startTime && <Text style={sg.time}>{startTime}</Text>}
          {endTime && endTime !== startTime && <Text style={sg.time}>{endTime}</Text>}
        </View>
      </View>

      {/* Image strip */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={sg.imageStrip} contentContainerStyle={sg.imageStripContent}>
        {segment.images.map((img, i) => (
          <ImageCard key={`${i}-${img.imagePath}`} image={img} deviceId={deviceId} size={120} />
        ))}
      </ScrollView>
    </View>
  );
};

// ── Main screen ───────────────────────────────────────────────────────────────
const BrowseScreen = () => {
  const deviceId = useAppSelector(s => s.auth.deviceId);
  const navigation = useNavigation<NativeStackNavigationProp<RootStackParamList>>();
  const [dates, setDates] = useState<string[]>([]);
  const [selectedDate, setSelectedDate] = useState<string>(dayjs().format('YYYY-MM-DD'));
  const [initialDateSet, setInitialDateSet] = useState(false);
  const [availableHours, setAvailableHours] = useState<number[]>([]);
  const [selectedHour, setSelectedHour] = useState<number>(0);
  const [segments, setSegments] = useState<BrowseSegment[]>([]);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [summary, setSummary] = useState<DaySummary | null>(null);
  const [processing, setProcessing] = useState(false);
  const [calendarVisible, setCalendarVisible] = useState(false);
  const today = dayjs().format('YYYY-MM-DD');

  const totalImages = useMemo(() => segments.reduce((n, s) => n + s.images.length, 0), [segments]);

  useSWRNative(
    deviceId ? ['all-dates', deviceId] : null,
    () => getAllDates(deviceId).then(r => r.data as string[]),
    {
      refreshInterval: 5 * 60 * 1000,
      onSuccess: (d: string[]) => {
        setDates(d);
        if (!initialDateSet && d.length > 0) {
          setSelectedDate(d[d.length - 1]);
          setInitialDateSet(true);
        }
      },
    }
  );

  useEffect(() => {
    if (!deviceId || !selectedDate) { return; }
    setSummary(null);
    getDaySummary(deviceId, selectedDate)
      .then(res => setSummary(res.data))
      .catch(() => {});
  }, [deviceId, selectedDate]);

  const loadSegments = useCallback(async (date: string, hour: number, pg: number) => {
    if (!deviceId) { return; }
    setLoading(true);
    try {
      const res = await getImagesByHour(deviceId, date, hour, pg);
      const { segments: segs, available_hours, total_pages } = res.data as any;
      const newSegs: BrowseSegment[] = segs ?? [];
      setSegments(pg === 1 ? newSegs : prev => [...prev, ...newSegs]);
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
    loadSegments(selectedDate, selectedHour, 1);
  }, [selectedDate, selectedHour, deviceId]);


  const isToday = selectedDate === today;

  const {} = useSWRNative(
    [selectedDate, selectedHour, deviceId],
    () => {
      setPage(1);
      loadSegments(selectedDate, selectedHour, 1);
    },
    { refreshInterval: isToday ? 30 * 1000 : 0 }
  );

  const { data: currentStatus } = useSWRNative(
    isToday && deviceId ? ['current-status', deviceId] : null,
    () => getCurrentStatus(deviceId).then(r => r.data),
    { refreshInterval: 30 * 1000 }
  );


  const loadMore = () => {
    if (page < totalPages && !loading) {
      const next = page + 1;
      setPage(next);
      loadSegments(selectedDate, selectedHour, next);
    }
  };

  return (
    <View style={styles.container}>
      <CalendarPicker
        visible={calendarVisible}
        availableDates={dates}
        selectedDate={selectedDate}
        onSelect={d => { setSelectedDate(d); setPage(1); }}
        onClose={() => setCalendarVisible(false)}
      />

      {/* Hour strip */}
      {availableHours.length > 0 && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false}
          style={styles.hourStrip} contentContainerStyle={styles.hourStripContent}>
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

      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.scrollContent}
        onScroll={({ nativeEvent }) => {
          const { layoutMeasurement, contentOffset, contentSize } = nativeEvent;
          const nearBottom = layoutMeasurement.height + contentOffset.y >= contentSize.height - 400;
          if (nearBottom) loadMore();
        }}
        scrollEventThrottle={200}
      >
        {/* Day header */}
        <View style={styles.header}>
          <TouchableOpacity onPress={() => setCalendarVisible(true)} style={styles.headerDateBtn}>
            <Text style={styles.headerDate}>{dayjs(selectedDate).format('dddd, D MMMM YYYY')}</Text>
            <Text style={styles.headerDateCaret}> ▾</Text>
          </TouchableOpacity>
          <View style={styles.headerRight}>
            <Text style={styles.headerCount}>{totalImages} photos</Text>
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

        {/* Current status (today only) */}
        {currentStatus && isToday && (
          <CurrentStatusCard status={currentStatus} deviceId={deviceId} />
        )}

        {/* Day summary */}
        {summary && <DaySummaryCard summary={summary} deviceId={deviceId} />}

        {/* Segments */}
        {loading && segments.length === 0 ? (
          <ActivityIndicator style={styles.loader} color={COLORS.primary} size="large" />
        ) : segments.length === 0 ? (
          <View style={styles.empty}>
            <Text style={styles.emptyText}>No images for this hour</Text>
          </View>
        ) : (
          segments.map((seg, i) => (
            <SegmentBlock key={i} segment={seg} deviceId={deviceId} index={i} />
          ))
        )}

        {loading && segments.length > 0 && (
          <ActivityIndicator color={COLORS.primary} style={{ marginVertical: 16 }} />
        )}
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.background },
  scroll: { flex: 1 },
  scrollContent: { paddingBottom: 32 },
  hourStrip: { maxHeight: 44, backgroundColor: COLORS.surface, borderBottomWidth: 1, borderColor: COLORS.divider },
  hourStripContent: { paddingHorizontal: 8, paddingVertical: 8, gap: 6 },
  hourChip: {
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: 12,
    backgroundColor: COLORS.background, borderWidth: 1, borderColor: COLORS.divider,
  },
  hourChipActive: { backgroundColor: COLORS.secondary, borderColor: COLORS.secondary },
  hourChipText: { fontSize: 11, color: COLORS.textSecondary },
  hourChipTextActive: { color: '#fff', fontWeight: '600' },
  header: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    paddingHorizontal: 14, paddingVertical: 8,
  },
  headerDateBtn: { flexDirection: 'row', alignItems: 'center', flex: 1 },
  headerDate: { fontSize: 13, fontWeight: '600', color: COLORS.textPrimary },
  headerDateCaret: { fontSize: 11, color: COLORS.primary, fontWeight: '700' },
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
  loader: { marginTop: 60 },
  empty: { padding: 40, alignItems: 'center' },
  emptyText: { color: COLORS.textSecondary, fontSize: 14 },
});

// Segment block styles
const sg = StyleSheet.create({
  block: {
    marginHorizontal: 8, marginTop: 10,
    backgroundColor: COLORS.surface, borderRadius: 12, overflow: 'hidden', elevation: 1,
  },
  locationRow: {
    flexDirection: 'row', alignItems: 'flex-start',
    paddingHorizontal: 12, paddingTop: 10, paddingBottom: 4, gap: 6,
  },
  locationIcon: { fontSize: 13, marginTop: 1 },
  locationText: { flex: 1 },
  locationName: { fontSize: 13, fontWeight: '600', color: COLORS.secondary },
  locationSub: { fontSize: 11, color: COLORS.textSecondary, marginTop: 1 },
  infoRow: {
    flexDirection: 'row', alignItems: 'flex-start',
    paddingHorizontal: 12, paddingVertical: 6, gap: 8,
    borderTopWidth: 1, borderColor: COLORS.divider,
  },
  infoLeft: { flex: 1 },
  activityRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 6, marginBottom: 3 },
  activity: { fontSize: 14, fontWeight: '700', color: COLORS.textPrimary, textTransform: 'capitalize' },
  groupChip: {
    paddingHorizontal: 7, paddingVertical: 2, borderRadius: 10,
  },
  groupChipText: { fontSize: 10, fontWeight: '600', color: 'rgba(0,0,0,0.65)' },
  confidence: { fontSize: 11 },
  meta: { fontSize: 11, color: COLORS.textSecondary, marginBottom: 3 },
  description: { fontSize: 12, color: COLORS.textSecondary, fontStyle: 'italic', lineHeight: 17 },
  timeCol: { alignItems: 'flex-end', minWidth: 52 },
  time: { fontSize: 11, color: COLORS.textSecondary },
  imageStrip: { borderTopWidth: 1, borderColor: COLORS.divider },
  imageStripContent: { paddingHorizontal: 8, paddingVertical: 8, gap: 6 },
});

// Current status card styles
const cs = StyleSheet.create({
  card: {
    marginHorizontal: 10, marginTop: 8, marginBottom: 4,
    backgroundColor: COLORS.surface, borderRadius: 12, elevation: 2, overflow: 'hidden',
    borderWidth: 1, borderColor: COLORS.divider,
  },
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 12, paddingVertical: 10, gap: 8,
  },
  headerLeft: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  title: { fontSize: 13, fontWeight: '700', color: COLORS.textPrimary },
  liveChip: {
    backgroundColor: COLORS.success, borderRadius: 8,
    paddingHorizontal: 7, paddingVertical: 2,
  },
  liveChipText: { fontSize: 10, fontWeight: '700', color: '#1a5c3a' },
  offlineText: { fontSize: 11, color: COLORS.textSecondary },
  sensorRow: { maxHeight: 22, flexShrink: 1 },
  sensorRowContent: { gap: 10, paddingHorizontal: 4 },
  sensorItem: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  sensorLabel: { fontSize: 10, color: COLORS.textSecondary },
  divider: { height: 1, backgroundColor: COLORS.divider },
  body: { flexDirection: 'row', padding: 12, gap: 10 },
  thumbnail: { width: 64, height: 64, borderRadius: 8, flexShrink: 0 },
  bodyText: { flex: 1, gap: 3 },
  activityText: { fontSize: 13, fontWeight: '600', color: COLORS.textPrimary },
  activityDesc: { fontSize: 11, color: COLORS.textSecondary, lineHeight: 16 },
  locationText: { fontSize: 11, color: COLORS.textSecondary },
  sinceText: { fontSize: 11, color: COLORS.textSecondary },
  summaryText: { fontSize: 12, color: COLORS.textSecondary, fontStyle: 'italic', padding: 12, lineHeight: 18 },
});

// Day summary card styles
const ss = StyleSheet.create({
  card: {
    marginHorizontal: 10, marginBottom: 10, borderRadius: 8,
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

  overviewRow: {
    flexDirection: 'row', alignItems: 'center',
    paddingVertical: 12,
    borderTopWidth: 1, borderColor: COLORS.divider,
  },
  overviewStat: { flex: 1, alignItems: 'center' },
  overviewValue: { fontSize: 20, fontWeight: '700', color: COLORS.textPrimary },
  overviewLabel: { fontSize: 11, color: COLORS.textSecondary, marginTop: 2 },
  overviewDivider: { width: 1, height: 36, backgroundColor: COLORS.divider },

  section: {
    paddingHorizontal: 14, paddingVertical: 10,
    borderTopWidth: 1, borderColor: COLORS.divider,
  },
  sectionLabel: {
    fontSize: 10, fontWeight: '700', color: COLORS.textSecondary,
    letterSpacing: 0.6, textTransform: 'uppercase', marginBottom: 8,
  },

  summaryText: {
    fontSize: 13, color: COLORS.textPrimary, lineHeight: 19, fontStyle: 'italic',
  },

  timelineBar: { flexDirection: 'row', height: 28, borderRadius: 4, overflow: 'hidden' },
  timelineSegment: { height: '100%' },

  barRow: { marginBottom: 8 },
  barLabelRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 4 },
  barName: { flex: 1, fontSize: 12, color: COLORS.textPrimary },
  barPct: { fontSize: 11, color: COLORS.textSecondary },
  barTrack: { height: 6, backgroundColor: COLORS.divider, borderRadius: 3, overflow: 'hidden' },
  barFill: { height: '100%', backgroundColor: COLORS.primary, borderRadius: 3 },
  catDot: { width: 8, height: 8, borderRadius: 4, marginRight: 6 },

  burstGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  burstCell: {
    padding: 10, backgroundColor: COLORS.background,
    borderRadius: 8, alignItems: 'center', minWidth: 68,
  },
  burstCount: { fontSize: 22, fontWeight: '700', color: COLORS.textPrimary },
  burstName: { fontSize: 10, color: COLORS.textSecondary, textAlign: 'center', marginTop: 2 },

  periodTabsRow: { gap: 6, paddingBottom: 8 },
  periodTab: {
    paddingHorizontal: 12, paddingVertical: 5, borderRadius: 16,
  },
  periodTabText: { fontSize: 12, fontWeight: '600', color: '#444' },
  periodTabTextActive: { color: '#fff' },
  periodCard: {
    marginTop: 4, marginBottom: 10,
    backgroundColor: COLORS.background, borderRadius: 10, overflow: 'hidden',
  },
  occurrenceRow: { paddingHorizontal: 10, paddingVertical: 8, gap: 6 },
  occurrenceTab: {
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: 12,
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.divider,
  },
  occurrenceTabActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  occurrenceTabText: { fontSize: 11, color: COLORS.textSecondary },
  occurrenceTabTextActive: { color: '#fff', fontWeight: '600' },
  periodSummary: {
    fontSize: 12, fontStyle: 'italic', color: COLORS.textPrimary,
    paddingHorizontal: 12, paddingBottom: 8,
  },
  periodImages: { paddingHorizontal: 10, paddingBottom: 12, gap: 8 },
  periodImageWrap: { alignItems: 'center' },
  periodImage: { width: 120, height: 90, borderRadius: 8 },
  periodImageTime: { fontSize: 9, color: COLORS.textSecondary, marginTop: 3 },

});

// Calendar picker styles
const cal = StyleSheet.create({
  overlay: {
    flex: 1, backgroundColor: 'rgba(0,0,0,0.45)',
    justifyContent: 'center', alignItems: 'center',
  },
  sheet: {
    backgroundColor: COLORS.surface, borderRadius: 18,
    padding: 16, width: 320, elevation: 8,
  },
  header: {
    flexDirection: 'row', alignItems: 'center',
    justifyContent: 'space-between', marginBottom: 12,
  },
  navBtn: { padding: 8 },
  navText: { fontSize: 24, color: COLORS.primary, fontWeight: '700' },
  navDisabled: { color: COLORS.divider },
  monthLabel: { fontSize: 15, fontWeight: '700', color: COLORS.textPrimary },
  weekRow: { flexDirection: 'row' },
  weekDay: {
    flex: 1, textAlign: 'center', fontSize: 11,
    color: COLORS.textSecondary, fontWeight: '600', paddingBottom: 6,
  },
  cell: {
    flex: 1, aspectRatio: 1, alignItems: 'center',
    justifyContent: 'center', borderRadius: 100, margin: 2,
  },
  cellAvailable: { backgroundColor: COLORS.primary + '22' },
  cellSelected: { backgroundColor: COLORS.primary },
  cellText: { fontSize: 13, color: COLORS.textSecondary },
  cellTextSelected: { color: '#fff', fontWeight: '700' },
  cellTextDisabled: { color: COLORS.divider },
});

export default BrowseScreen;

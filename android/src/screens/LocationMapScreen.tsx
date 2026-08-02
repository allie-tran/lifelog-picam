import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import WebView from 'react-native-webview';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import dayjs from 'dayjs';
import { getAllDates, getGpsByDate, GpsPoint, GpsTrackData } from '../api/browsing';
import { useAppSelector } from '../store';
import { COLORS } from '../constants';
import type { RootStackParamList } from '../types';

const MAPTILER_KEY = 'bcAmE6kzFa3YgI6GTxUH';

type Props = NativeStackScreenProps<RootStackParamList, 'LocationMap'>;

const buildMapHtml = (points: GpsPoint[]) => {
  const hasPoints = points.length > 0;
  const center = hasPoints
    ? `[${points[0].latitude}, ${points[0].longitude}]`
    : '[20, 0]';
  const zoom = hasPoints ? 13 : 2;
  const pointsJson = JSON.stringify(points.map(p => [p.latitude, p.longitude]));

  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box;}
html,body,#map{width:100%;height:100%;background:#0d1117;}
</style>
</head>
<body>
<div id="map"></div>
<script>
var map = L.map('map', { center: ${center}, zoom: ${zoom}, zoomControl: true });
L.tileLayer('https://api.maptiler.com/maps/dataviz-v4/{z}/{x}/{y}.png?key=${MAPTILER_KEY}',
  { attribution: '', tileSize: 512, zoomOffset: -1 }).addTo(map);

var pts = ${pointsJson};
if (pts.length > 0) {
  // Draw polyline track
  var line = L.polyline(pts, { color: '#16A299', weight: 3, opacity: 0.8 }).addTo(map);
  map.fitBounds(line.getBounds(), { padding: [30, 30] });

  // Start marker (green)
  L.circleMarker(pts[pts.length - 1], {
    radius: 9, color: '#27ae60', fillColor: '#27ae60', fillOpacity: 1, weight: 2
  }).bindTooltip('Start').addTo(map);

  // End marker (red)
  L.circleMarker(pts[0], {
    radius: 9, color: '#c0392b', fillColor: '#c0392b', fillOpacity: 1, weight: 2
  }).bindTooltip('End').addTo(map);
}
</script>
</body>
</html>`;
};

const NO_DATA_HTML = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body{background:#0d1117;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}
p{color:rgba(255,255,255,0.4);font-family:sans-serif;font-size:14px;text-align:center;}
</style>
</head>
<body><p>No GPS data for this date.</p></body>
</html>`;

const LocationMapScreen = ({ route }: Props) => {
  const deviceId = useAppSelector(s => s.auth.deviceId);
  const [dates, setDates] = useState<string[]>([]);
  const [selectedDate, setSelectedDate] = useState<string>(
    route.params?.date ?? dayjs().format('YYYY-MM-DD'),
  );
  const [points, setPoints] = useState<GpsPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const webviewRef = useRef<WebView>(null);

  useEffect(() => {
    if (!deviceId) { return; }
    getAllDates(deviceId)
      .then(res => {
        const d = res.data as string[];
        setDates(d);
        if (d.length > 0 && !route.params?.date) {
          setSelectedDate(d[0]);
        }
      })
      .catch(() => {});
  }, [deviceId]);

  const loadPoints = useCallback(async (date: string) => {
    if (!deviceId) { return; }
    setLoading(true);
    setPoints([]);
    try {
      const res = await getGpsByDate(deviceId, date);
      const data = res.data as GpsTrackData;
      setPoints(data.rawGps?.length ? data.rawGps : (data.imageGps ?? []));
    } catch {
      setPoints([]);
    } finally {
      setLoading(false);
    }
  }, [deviceId]);

  useEffect(() => {
    loadPoints(selectedDate);
  }, [selectedDate, loadPoints]);

  const mapHtml = points.length > 0 ? buildMapHtml(points) : NO_DATA_HTML;

  return (
    <View style={styles.container}>
      {/* Date strip */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.dateStrip}
        contentContainerStyle={styles.dateStripContent}
      >
        {dates.map(d => (
          <TouchableOpacity
            key={d}
            style={[styles.dateChip, selectedDate === d && styles.dateChipActive]}
            onPress={() => setSelectedDate(d)}
          >
            <Text style={[styles.dateChipText, selectedDate === d && styles.dateChipTextActive]}>
              {dayjs(d).format('D MMM')}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {/* Stats bar */}
      <View style={styles.statsBar}>
        <Text style={styles.statsDate}>{dayjs(selectedDate).format('dddd, D MMMM YYYY')}</Text>
        <Text style={styles.statsCount}>
          {loading ? '…' : `${points.length} GPS point${points.length !== 1 ? 's' : ''}`}
        </Text>
      </View>

      {/* Map */}
      <View style={styles.mapContainer}>
        {loading && (
          <View style={styles.loaderOverlay}>
            <ActivityIndicator color={COLORS.secondary} size="large" />
          </View>
        )}
        <WebView
          ref={webviewRef}
          source={{ html: mapHtml }}
          style={styles.map}
          originWhitelist={['*']}
          javaScriptEnabled
          scrollEnabled={false}
        />
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.background },
  dateStrip: {
    maxHeight: 46, backgroundColor: COLORS.surface,
    borderBottomWidth: 1, borderColor: COLORS.divider,
  },
  dateStripContent: { paddingHorizontal: 8, paddingVertical: 8, gap: 6 },
  dateChip: {
    paddingHorizontal: 12, paddingVertical: 4, borderRadius: 20,
    borderWidth: 1, borderColor: COLORS.divider, backgroundColor: COLORS.background,
  },
  dateChipActive: { backgroundColor: COLORS.secondary, borderColor: COLORS.secondary },
  dateChipText: { fontSize: 12, color: COLORS.textSecondary },
  dateChipTextActive: { color: '#fff', fontWeight: '600' },
  statsBar: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    paddingHorizontal: 14, paddingVertical: 8,
    borderBottomWidth: 1, borderColor: COLORS.divider, backgroundColor: COLORS.surface,
  },
  statsDate: { fontSize: 13, fontWeight: '600', color: COLORS.textPrimary },
  statsCount: { fontSize: 12, color: COLORS.textSecondary },
  mapContainer: { flex: 1, position: 'relative' },
  map: { flex: 1 },
  loaderOverlay: {
    ...StyleSheet.absoluteFill,
    backgroundColor: 'rgba(253,252,240,0.7)',
    alignItems: 'center', justifyContent: 'center',
    zIndex: 10,
  },
});

export default LocationMapScreen;

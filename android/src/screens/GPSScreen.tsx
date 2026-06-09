import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  PermissionsAndroid,
  Platform,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import Geolocation from 'react-native-geolocation-service';
import WebView from 'react-native-webview';
import { COLORS } from '../constants';
import { useAppSelector } from '../store';
import { GPSPoint, getGPSByDate, processGPS } from '../api/gps';
import { getAllDates } from '../api/browsing';
import { startBackgroundGPS, stopBackgroundGPS, isBackgroundGPSRunning } from '../services/backgroundGPS';
import dayjs from 'dayjs';

const MAPTILER_KEY = 'bcAmE6kzFa3YgI6GTxUH';

const MAP_HTML = `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    * { margin:0; padding:0; box-sizing:border-box; }
    html,body { width:100%; height:100%; }
    #map { width:100%; height:100%; }
  </style>
</head>
<body>
<div id="map"></div>
<script>
  var GRADIENT = ['#3b82f6','#06b6d4','#22c55e','#eab308','#f97316','#ef4444'];
  function lerpColor(a,b,t){
    function p(h){return[parseInt(h.slice(1,3),16),parseInt(h.slice(3,5),16),parseInt(h.slice(5,7),16)];}
    var ca=p(a),cb=p(b);
    return 'rgb('+Math.round(ca[0]+(cb[0]-ca[0])*t)+','+Math.round(ca[1]+(cb[1]-ca[1])*t)+','+Math.round(ca[2]+(cb[2]-ca[2])*t)+')';
  }
  function getColor(t){
    var s=t*(GRADIENT.length-1), i=Math.min(Math.floor(s),GRADIENT.length-2);
    return lerpColor(GRADIENT[i],GRADIENT[i+1],s-i);
  }

  var map = L.map('map',{center:[53.3498,-6.2603],zoom:13});
  L.tileLayer('https://api.maptiler.com/maps/dataviz-v4/{z}/{x}/{y}.png?key=${MAPTILER_KEY}',
    {attribution:'&copy; MapTiler &copy; OpenStreetMap',tileSize:512,zoomOffset:-1}).addTo(map);

  var trackLayer = L.layerGroup().addTo(map);
  var currentMarker = null;

  function updateTrack(points){
    trackLayer.clearLayers();
    if(!points||points.length===0) return;
    for(var i=0;i<points.length-1;i++){
      var t=i/(points.length-1);
      L.polyline([[points[i].latitude,points[i].longitude],[points[i+1].latitude,points[i+1].longitude]],
        {color:getColor(t),weight:4,opacity:0.9}).addTo(trackLayer);
    }
    if(points.length>0){
      L.circleMarker([points[0].latitude,points[0].longitude],
        {radius:7,color:'#fff',weight:2,fillColor:'#3b82f6',fillOpacity:1})
        .bindPopup('Start').addTo(trackLayer);
      var last=points[points.length-1];
      L.circleMarker([last.latitude,last.longitude],
        {radius:7,color:'#fff',weight:2,fillColor:'#ef4444',fillOpacity:1})
        .bindPopup('End').addTo(trackLayer);
    }
    var lls=points.map(function(p){return[p.latitude,p.longitude];});
    map.fitBounds(L.latLngBounds(lls),{padding:[40,40]});
  }

  function updatePosition(lat,lon){
    if(currentMarker) currentMarker.remove();
    currentMarker=L.circleMarker([lat,lon],
      {radius:10,color:'#fff',weight:2,fillColor:'#6366f1',fillOpacity:1})
      .bindPopup('You are here').addTo(map);
  }

  function handleMsg(event){
    try{
      var msg=JSON.parse(event.data);
      if(msg.type==='track') updateTrack(msg.data);
      if(msg.type==='position') updatePosition(msg.lat,msg.lon);
    }catch(e){}
  }
  document.addEventListener('message',handleMsg);
  window.addEventListener('message',handleMsg);
</script>
</body>
</html>`;

const GPSScreen = () => {
  const deviceId = useAppSelector(s => s.auth.deviceId);

  const [dates, setDates] = useState<string[]>([]);
  const [selectedDate, setSelectedDate] = useState<string>('');
  const [track, setTrack] = useState<GPSPoint[]>([]);
  const [loadingTrack, setLoadingTrack] = useState(false);

  const [trackingEnabled, setTrackingEnabled] = useState(false);
  const [hasPermission, setHasPermission] = useState(false);
  const [currentPos, setCurrentPos] = useState<{ lat: number; lon: number } | null>(null);
  const [sensorDeviceId, setSensorDeviceId] = useState<string>('');

  const webViewRef = useRef<WebView | null>(null);
  const watchIdRef = useRef<number | null>(null);

  // ── Sensor device ID ──────────────────────────────────────────────────────
  useEffect(() => {
    AsyncStorage.getItem('sensorDeviceId').then(id => {
      if (id) {
        setSensorDeviceId(id);
      } else {
        const newId = 'rn-' + Math.random().toString(36).slice(2, 10);
        AsyncStorage.setItem('sensorDeviceId', newId);
        setSensorDeviceId(newId);
      }
    });
  }, []);

  // ── Date list ─────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!deviceId) { return; }
    getAllDates(deviceId).then(res => {
      const sorted = [...(res.data as string[])].sort((a, b) => b.localeCompare(a));
      setDates(sorted);
      if (sorted.length > 0) { setSelectedDate(sorted[0]); }
    }).catch(() => {});
  }, [deviceId]);

  // ── GPS track for selected date ───────────────────────────────────────────
  useEffect(() => {
    if (!selectedDate || !deviceId) { return; }
    setLoadingTrack(true);
    getGPSByDate(selectedDate, deviceId)
      .then(points => {
        setTrack(points);
        postToMap({ type: 'track', data: points });
      })
      .catch(() => {
        processGPS(deviceId, selectedDate).catch(() => {});
        setTrack([]);
        postToMap({ type: 'track', data: [] });
      })
      .finally(() => setLoadingTrack(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDate, deviceId]);

  // ── Restore state if service was already running ──────────────────────────
  useEffect(() => {
    if (isBackgroundGPSRunning()) {
      setTrackingEnabled(true);
      setHasPermission(true);
    }
    // On unmount: stop watchPosition only — leave BackgroundService running
    return () => { stopWatchPosition(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Start watchPosition for map updates when tracking + sensorId ready ────
  useEffect(() => {
    if (trackingEnabled && sensorDeviceId && hasPermission) {
      startWatchPosition();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trackingEnabled, sensorDeviceId, hasPermission]);

  // ── Helpers ───────────────────────────────────────────────────────────────
  const postToMap = useCallback((msg: object) => {
    webViewRef.current?.injectJavaScript(
      `(function(){ window.dispatchEvent(new MessageEvent('message',{data:${JSON.stringify(JSON.stringify(msg))}})); })();`
    );
  }, []);

  const startWatchPosition = () => {
    if (watchIdRef.current !== null) { return; }
    watchIdRef.current = Geolocation.watchPosition(
      pos => {
        const { latitude, longitude } = pos.coords;
        setCurrentPos({ lat: latitude, lon: longitude });
        postToMap({ type: 'position', lat: latitude, lon: longitude });
      },
      err => console.warn('GPS watch error:', err),
      { enableHighAccuracy: true, distanceFilter: 10, interval: 5000, fastestInterval: 2000 },
    );
  };

  const stopWatchPosition = () => {
    if (watchIdRef.current !== null) {
      Geolocation.clearWatch(watchIdRef.current);
      watchIdRef.current = null;
    }
  };

  const requestPermission = async (): Promise<boolean> => {
    if (Platform.OS !== 'android') { setHasPermission(true); return true; }
    const result = await PermissionsAndroid.request(
      PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION,
      {
        title: 'Location Permission',
        message: 'Lifelog needs your location to track your position.',
        buttonPositive: 'OK',
        buttonNegative: 'Cancel',
      },
    );
    const granted = result === PermissionsAndroid.RESULTS.GRANTED;
    setHasPermission(granted);
    if (!granted) {
      Alert.alert('Permission denied', 'Location permission is required for GPS tracking.');
    }
    return granted;
  };

  // ── Toggle handler ────────────────────────────────────────────────────────
  const handleToggle = async (enabled: boolean) => {
    if (enabled) {
      const ok = await requestPermission();
      if (!ok) { return; }
      setTrackingEnabled(true);
      // startWatchPosition is triggered by the effect above once hasPermission is set
      try {
        await startBackgroundGPS(sensorDeviceId, deviceId);
      } catch {
        Alert.alert('Error', 'Failed to start background GPS service.');
        setTrackingEnabled(false);
      }
    } else {
      setTrackingEnabled(false);
      stopWatchPosition();
      setCurrentPos(null);
      stopBackgroundGPS().catch(() => {});
    }
  };

  // ── Date navigation ───────────────────────────────────────────────────────
  const dateIndex = dates.indexOf(selectedDate);

  return (
    <View style={styles.container}>
      {/* Date navigation */}
      <View style={styles.dateBar}>
        <TouchableOpacity
          style={[styles.navBtn, dateIndex >= dates.length - 1 && styles.navBtnDisabled]}
          onPress={() => dateIndex < dates.length - 1 && setSelectedDate(dates[dateIndex + 1])}
          disabled={dateIndex >= dates.length - 1}
        >
          <Text style={styles.navBtnText}>‹</Text>
        </TouchableOpacity>
        <View style={styles.dateCenter}>
          <Text style={styles.dateText}>
            {selectedDate ? dayjs(selectedDate).format('ddd, D MMM YYYY') : 'No dates'}
          </Text>
          <Text style={styles.trackInfo}>
            {loadingTrack ? 'Loading…' : `${track.length} GPS points`}
          </Text>
        </View>
        <TouchableOpacity
          style={[styles.navBtn, dateIndex <= 0 && styles.navBtnDisabled]}
          onPress={() => dateIndex > 0 && setSelectedDate(dates[dateIndex - 1])}
          disabled={dateIndex <= 0}
        >
          <Text style={styles.navBtnText}>›</Text>
        </TouchableOpacity>
      </View>

      {/* Date chip strip */}
      {dates.length > 0 && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false}
          style={styles.strip} contentContainerStyle={styles.stripContent}>
          {dates.slice(0, 30).map(d => (
            <TouchableOpacity
              key={d}
              style={[styles.dateChip, d === selectedDate && styles.dateChipActive]}
              onPress={() => setSelectedDate(d)}
            >
              <Text style={[styles.dateChipText, d === selectedDate && styles.dateChipTextActive]}>
                {dayjs(d).format('D MMM')}
              </Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      )}

      {/* Map */}
      <View style={styles.map}>
        {loadingTrack && (
          <View style={styles.mapOverlay}>
            <ActivityIndicator size="large" color={COLORS.primary} />
          </View>
        )}
        <WebView
          ref={webViewRef}
          source={{ html: MAP_HTML }}
          style={styles.webview}
          javaScriptEnabled
          domStorageEnabled
          originWhitelist={['*']}
          mixedContentMode="always"
          onLoad={() => {
            if (track.length > 0) { postToMap({ type: 'track', data: track }); }
            if (currentPos) { postToMap({ type: 'position', lat: currentPos.lat, lon: currentPos.lon }); }
          }}
        />
      </View>

      {/* Tracking panel */}
      <View style={styles.trackingPanel}>
        <View style={styles.trackingRow}>
          <View style={{ flex: 1 }}>
            <View style={styles.trackingTitleRow}>
              <Text style={styles.trackingLabel}>Live GPS Tracking</Text>
              {trackingEnabled && (
                <View style={styles.bgBadge}>
                  <Text style={styles.bgBadgeText}>● Background</Text>
                </View>
              )}
            </View>
            <Text style={styles.trackingHint}>
              {trackingEnabled
                ? currentPos
                  ? `${currentPos.lat.toFixed(5)}, ${currentPos.lon.toFixed(5)}`
                  : 'Getting location…'
                : 'Tap to start — stays active when you switch tabs'}
            </Text>
          </View>
          <Switch
            value={trackingEnabled}
            onValueChange={handleToggle}
            thumbColor={trackingEnabled ? COLORS.primary : COLORS.divider}
            trackColor={{ false: COLORS.divider, true: COLORS.secondary }}
          />
        </View>
        {trackingEnabled && sensorDeviceId ? (
          <Text style={styles.deviceIdText} numberOfLines={1}>Sensor ID: {sensorDeviceId}</Text>
        ) : null}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.background },
  dateBar: {
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: COLORS.surface, paddingVertical: 8, paddingHorizontal: 4,
    borderBottomWidth: 1, borderBottomColor: COLORS.divider,
  },
  navBtn: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center' },
  navBtnDisabled: { opacity: 0.3 },
  navBtnText: { fontSize: 24, color: COLORS.primary, fontWeight: '600' },
  dateCenter: { flex: 1, alignItems: 'center' },
  dateText: { fontSize: 15, fontWeight: '700', color: COLORS.textPrimary },
  trackInfo: { fontSize: 11, color: COLORS.textSecondary, marginTop: 2 },
  strip: { maxHeight: 44, backgroundColor: COLORS.surface, borderBottomWidth: 1, borderBottomColor: COLORS.divider },
  stripContent: { paddingHorizontal: 8, paddingVertical: 6, gap: 6 },
  dateChip: {
    paddingHorizontal: 12, paddingVertical: 4, borderRadius: 16,
    backgroundColor: COLORS.background, borderWidth: 1, borderColor: COLORS.divider,
  },
  dateChipActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  dateChipText: { fontSize: 12, color: COLORS.textSecondary },
  dateChipTextActive: { color: '#fff', fontWeight: '600' },
  map: { flex: 1, position: 'relative' },
  webview: { flex: 1 },
  mapOverlay: {
    ...StyleSheet.absoluteFill,
    zIndex: 10, alignItems: 'center', justifyContent: 'center',
    backgroundColor: 'rgba(255,255,255,0.6)',
  },
  trackingPanel: {
    backgroundColor: COLORS.surface, paddingHorizontal: 16, paddingVertical: 12,
    borderTopWidth: 1, borderTopColor: COLORS.divider, elevation: 4,
  },
  trackingRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  trackingTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  trackingLabel: { fontSize: 14, fontWeight: '700', color: COLORS.textPrimary },
  bgBadge: { backgroundColor: '#d4edda', paddingHorizontal: 8, paddingVertical: 2, borderRadius: 10 },
  bgBadgeText: { fontSize: 10, color: '#155724', fontWeight: '700' },
  trackingHint: { fontSize: 12, color: COLORS.textSecondary, marginTop: 3, maxWidth: 260 },
  deviceIdText: { fontSize: 10, color: COLORS.textSecondary, marginTop: 6 },
});

export default GPSScreen;

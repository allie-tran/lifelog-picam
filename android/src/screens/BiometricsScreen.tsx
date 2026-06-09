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
import dayjs from 'dayjs';
import { COLORS } from '../constants';
import { useAppSelector } from '../store';
import { getAllDates } from '../api/browsing';
import { getSensorLogs, MeasurementRecord } from '../api/admin';

const SENSORS = ['heartrate', 'ppi', 'accelerometer', 'gyroscope', 'magnetometer', 'ppg'];
const SENSOR_ICONS: Record<string, string> = {
  heartrate: '❤️', ppi: '💓', accelerometer: '📈',
  gyroscope: '🌀', magnetometer: '🧲', ppg: '🔴',
};

const CHART_HTML = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box;}
html,body{width:100%;height:100%;background:#FDFCF0;font-family:sans-serif;}
canvas{display:block;}
.msg{display:flex;align-items:center;justify-content:center;height:100%;color:#636E72;font-size:13px;padding:20px;text-align:center;}
</style>
</head>
<body>
<div id="msg" class="msg">Select a date and sensor above</div>
<canvas id="c" style="display:none;width:100%;height:100%;"></canvas>
<script>
var inst=null;
var PAL=['#16A299','#FF9E7D','#8E44AD','#e74c3c','#3498db','#f39c12'];
function show(labels,datasets){
  document.getElementById('msg').style.display='none';
  var canvas=document.getElementById('c');
  canvas.style.display='block';
  if(inst){inst.destroy();}
  inst=new Chart(canvas.getContext('2d'),{
    type:'line',
    data:{
      labels:labels,
      datasets:datasets.map(function(d,i){
        return{label:d.label,data:d.data,borderColor:PAL[i%PAL.length],
          backgroundColor:PAL[i%PAL.length]+'20',borderWidth:1.5,
          pointRadius:0,spanGaps:true,tension:0.2};
      })
    },
    options:{
      responsive:true,maintainAspectRatio:false,
      animation:{duration:0},
      plugins:{legend:{position:'bottom',labels:{font:{size:10},boxWidth:10,padding:8}}},
      scales:{
        x:{ticks:{maxTicksLimit:8,font:{size:9},maxRotation:0}},
        y:{ticks:{font:{size:9}}}
      }
    }
  });
}
function handleMsg(e){
  try{
    var m=JSON.parse(e.data);
    if(m.type==='data') show(m.labels,m.datasets);
    if(m.type==='loading'){
      document.getElementById('c').style.display='none';
      document.getElementById('msg').style.display='flex';
      document.getElementById('msg').textContent='Loading…';
    }
    if(m.type==='empty'){
      document.getElementById('c').style.display='none';
      document.getElementById('msg').style.display='flex';
      document.getElementById('msg').textContent='No '+m.sensor+' data for this date';
    }
  }catch(err){}
}
document.addEventListener('message',handleMsg);
window.addEventListener('message',handleMsg);
</script>
</body>
</html>`;

const MAX_POINTS = 300;

function prepareChartData(
  records: MeasurementRecord[],
  sensorKey: string,
): { labels: string[]; datasets: { label: string; data: (number | null)[] }[] } | null {
  if (!records || records.length === 0) { return null; }
  const step = Math.max(1, Math.floor(records.length / MAX_POINTS));
  const sampled = records.filter((_, i) => i % step === 0);
  const labels = sampled.map(r => {
    const d = new Date(r.timeStamp * 1000);
    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
  });
  const subKeys = Object.keys(sampled[0]?.values ?? {});
  const datasets = subKeys.map(sk => ({
    label: `${sensorKey} · ${sk}`,
    data: sampled.map(r => r.values[sk] ?? null),
  }));
  return { labels, datasets };
}

const BiometricsScreen = () => {
  const deviceId = useAppSelector(s => s.auth.deviceId);
  const [dates, setDates] = useState<string[]>([]);
  const [selectedDate, setSelectedDate] = useState('');
  const [sensor, setSensor] = useState('heartrate');
  const [loading, setLoading] = useState(false);
  const webViewRef = useRef<WebView | null>(null);

  useEffect(() => {
    if (!deviceId) { return; }
    getAllDates(deviceId)
      .then(res => {
        const sorted = [...(res.data as string[])].sort((a, b) => b.localeCompare(a));
        setDates(sorted);
        if (sorted.length > 0) { setSelectedDate(sorted[0]); }
      })
      .catch(() => {});
  }, [deviceId]);

  const postToChart = useCallback((msg: object) => {
    webViewRef.current?.injectJavaScript(
      `(function(){window.dispatchEvent(new MessageEvent('message',{data:${JSON.stringify(JSON.stringify(msg))}}));})();`,
    );
  }, []);

  const fetchSensorData = useCallback(async (date: string, sensorType: string) => {
    if (!date || !deviceId) { return; }
    setLoading(true);
    postToChart({ type: 'loading' });
    try {
      const res = await getSensorLogs(sensorType, date, deviceId);
      const records = res.data.logs[sensorType] ?? [];
      if (records.length === 0) {
        postToChart({ type: 'empty', sensor: sensorType });
      } else {
        const chartData = prepareChartData(records, sensorType);
        if (chartData) {
          postToChart({ type: 'data', ...chartData });
        } else {
          postToChart({ type: 'empty', sensor: sensorType });
        }
      }
    } catch {
      postToChart({ type: 'empty', sensor: sensorType });
    } finally {
      setLoading(false);
    }
  }, [deviceId, postToChart]);

  useEffect(() => {
    if (selectedDate && sensor) { fetchSensorData(selectedDate, sensor); }
  }, [selectedDate, sensor, fetchSensorData]);

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
        <Text style={styles.dateText}>
          {selectedDate ? dayjs(selectedDate).format('ddd, D MMM YYYY') : 'No dates'}
        </Text>
        <TouchableOpacity
          style={[styles.navBtn, dateIndex <= 0 && styles.navBtnDisabled]}
          onPress={() => dateIndex > 0 && setSelectedDate(dates[dateIndex - 1])}
          disabled={dateIndex <= 0}
        >
          <Text style={styles.navBtnText}>›</Text>
        </TouchableOpacity>
      </View>

      {/* Date chip strip */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.strip}
        contentContainerStyle={styles.stripContent}>
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

      {/* Sensor type picker */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.strip}
        contentContainerStyle={styles.stripContent}>
        {SENSORS.map(s => (
          <TouchableOpacity
            key={s}
            style={[styles.sensorChip, sensor === s && styles.sensorChipActive]}
            onPress={() => setSensor(s)}
          >
            <Text style={[styles.sensorChipText, sensor === s && styles.sensorChipTextActive]}>
              {SENSOR_ICONS[s]} {s}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {/* Chart */}
      <View style={styles.chartArea}>
        {loading && (
          <View style={styles.chartOverlay}>
            <ActivityIndicator size="large" color={COLORS.primary} />
          </View>
        )}
        <WebView
          ref={webViewRef}
          source={{ html: CHART_HTML }}
          style={styles.webview}
          javaScriptEnabled
          domStorageEnabled
          originWhitelist={['*']}
          mixedContentMode="always"
          onLoad={() => {
            if (selectedDate && sensor) { fetchSensorData(selectedDate, sensor); }
          }}
        />
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
  dateText: { flex: 1, textAlign: 'center', fontSize: 14, fontWeight: '700', color: COLORS.textPrimary },
  strip: { maxHeight: 44, backgroundColor: COLORS.surface, borderBottomWidth: 1, borderBottomColor: COLORS.divider },
  stripContent: { paddingHorizontal: 8, paddingVertical: 6, gap: 6 },
  dateChip: {
    paddingHorizontal: 12, paddingVertical: 4, borderRadius: 16,
    backgroundColor: COLORS.background, borderWidth: 1, borderColor: COLORS.divider,
  },
  dateChipActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  dateChipText: { fontSize: 12, color: COLORS.textSecondary },
  dateChipTextActive: { color: '#fff', fontWeight: '600' },
  sensorChip: {
    paddingHorizontal: 12, paddingVertical: 4, borderRadius: 16,
    backgroundColor: COLORS.background, borderWidth: 1, borderColor: COLORS.divider,
  },
  sensorChipActive: { backgroundColor: COLORS.secondary, borderColor: COLORS.secondary },
  sensorChipText: { fontSize: 12, color: COLORS.textSecondary },
  sensorChipTextActive: { color: '#fff', fontWeight: '600' },
  chartArea: { flex: 1, position: 'relative' },
  webview: { flex: 1 },
  chartOverlay: {
    ...StyleSheet.absoluteFill,
    zIndex: 10, alignItems: 'center', justifyContent: 'center',
    backgroundColor: 'rgba(253,252,240,0.7)',
  },
});

export default BiometricsScreen;

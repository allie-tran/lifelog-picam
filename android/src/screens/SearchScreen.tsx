import React, { useCallback, useEffect, useRef, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  ActivityIndicator,
  FlatList,
  Keyboard,
  Modal,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import WebView from 'react-native-webview';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';
import {
  changeSegmentActivity,
  getAllDates,
  parseQueryFilters,
  searchImages,
} from '../api/browsing';
import ImageCard from '../components/ImageCard';
import ResultSummaryBar from '../components/ResultSummaryBar';
import TimeHeatmap from '../components/TimeHeatmap';
import { useAppDispatch, useAppSelector } from '../store';
import {
  clearHistory,
  pushToHistory,
  removeFromHistory,
  setSearchQuery,
} from '../store/slices/searchSlice';
import { COLORS, config, formatTimeTz } from '../constants';
import { CountItem, ImageObject, LocationSummaryItem, SearchQuery } from '../types';

dayjs.extend(utc);
dayjs.extend(timezone);

const SEG_PAGE = 20;   // segments loaded per page
const MAPTILER_KEY = 'bcAmE6kzFa3YgI6GTxUH';

const MAP_HTML = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box;}
html,body{width:100%;height:100%;background:#111;}
#map{width:100%;height:calc(100% - 44px);}
#toolbar{height:44px;display:flex;align-items:center;gap:8px;padding:0 10px;background:#1a1a1a;border-bottom:1px solid #333;}
.btn{padding:5px 12px;border-radius:16px;border:1.5px solid rgba(255,255,255,0.35);background:transparent;color:#fff;font-size:11px;font-weight:600;}
.btn.on{background:#16A299;border-color:#16A299;}
.btn.go{background:#27ae60;border-color:#27ae60;}
.btn.clr{background:#c0392b;border-color:#c0392b;}
#hint{flex:1;color:rgba(255,255,255,0.45);font-size:10px;text-align:center;}
</style>
</head>
<body>
<div id="toolbar">
  <button class="btn" id="dBtn" onclick="toggleDraw()">📦 Draw Box</button>
  <span id="hint">Draw a box to filter by location</span>
  <button class="btn go" id="aBtn" style="display:none" onclick="applyBounds()">Apply</button>
  <button class="btn clr" id="cBtn" style="display:none" onclick="clearRect()">Clear</button>
</div>
<div id="map"></div>
<script>
var map=L.map('map',{center:[20,0],zoom:2});
L.tileLayer('https://api.maptiler.com/maps/dataviz-v4/{z}/{x}/{y}.png?key=${MAPTILER_KEY}',
  {attribution:'',tileSize:512,zoomOffset:-1}).addTo(map);
var drawMode=false,firstPt=null,cornerMark=null,rect=null,currentBounds=null;
function setHint(t){document.getElementById('hint').textContent=t;}
function toggleDraw(){
  drawMode=!drawMode;firstPt=null;
  var b=document.getElementById('dBtn');
  if(drawMode){b.textContent='✕ Cancel';b.className='btn on';map.dragging.disable();map.touchZoom.disable();map.scrollWheelZoom.disable();setHint('Tap first corner');}
  else{b.textContent='📦 Draw Box';b.className='btn';map.dragging.enable();map.touchZoom.enable();map.scrollWheelZoom.enable();if(cornerMark){map.removeLayer(cornerMark);cornerMark=null;}setHint(currentBounds?'Tap Apply to search':'Draw a box to filter by location');}
}
function applyBounds(){if(!currentBounds)return;window.ReactNativeWebView&&window.ReactNativeWebView.postMessage(JSON.stringify({type:'bounds',bounds:currentBounds}));}
function clearRect(){if(rect){map.removeLayer(rect);rect=null;}currentBounds=null;document.getElementById('aBtn').style.display='none';document.getElementById('cBtn').style.display='none';setHint('Draw a box to filter by location');window.ReactNativeWebView&&window.ReactNativeWebView.postMessage(JSON.stringify({type:'clear'}));}
map.on('click',function(e){
  if(!drawMode)return;
  if(!firstPt){firstPt=e.latlng;if(cornerMark)map.removeLayer(cornerMark);cornerMark=L.circleMarker(firstPt,{radius:7,color:'#16A299',fillColor:'#16A299',fillOpacity:1}).addTo(map);setHint('Tap second corner');}
  else{var lb=L.latLngBounds(firstPt,e.latlng);if(rect)map.removeLayer(rect);if(cornerMark){map.removeLayer(cornerMark);cornerMark=null;}rect=L.rectangle(lb,{color:'#16A299',weight:2,fillColor:'#16A299',fillOpacity:0.1}).addTo(map);currentBounds=[lb.getWest(),lb.getSouth(),lb.getEast(),lb.getNorth()];firstPt=null;toggleDraw();document.getElementById('aBtn').style.display='inline-block';document.getElementById('cBtn').style.display='inline-block';setHint('Tap Apply to search within box');}
});
</script>
</body>
</html>`;

const TIME_OF_DAY_OPTIONS = ['morning', 'afternoon', 'midday', 'evening', 'night'];
const DAY_OF_WEEK_OPTIONS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const MONTH_OPTIONS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

const FilterChip = ({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) => (
  <TouchableOpacity style={[styles.filterChip, active && styles.filterChipActive]} onPress={onPress}>
    <Text style={[styles.filterChipText, active && styles.filterChipTextActive]}>
      {label.charAt(0).toUpperCase() + label.slice(1)}
    </Text>
  </TouchableOpacity>
);

// ── Segment group row ─────────────────────────────────────────────────────────
interface SegmentGroupProps {
  segment: ImageObject[];
  deviceId: string;
  onEditActivity: (segment: ImageObject[]) => void;
}

const SegmentGroup = ({ segment, deviceId, onEditActivity }: SegmentGroupProps) => {
  const first = segment[0];
  const last = segment[segment.length - 1];
  const tz = first.timezone || config.defaultTimezone;
  const timeRange = `${formatTimeTz(first.timestamp, tz)} – ${formatTimeTz(last.timestamp, tz)}`;

  return (
    <View style={segStyles.container}>
      <TouchableOpacity
        style={segStyles.header}
        onLongPress={() => onEditActivity(segment)}
        delayLongPress={500}
        activeOpacity={0.7}
      >
        <Text style={segStyles.time}>
          {formatTimeTz(first.timestamp, tz)} · {timeRange}
        </Text>
        {first.description ? (
          <Text style={segStyles.activity} numberOfLines={2}>{first.description}</Text>
        ) : (
          <Text style={segStyles.noActivity}>No description — hold to add</Text>
        )}
        <Text style={segStyles.count}>{segment.length} photo{segment.length !== 1 ? 's' : ''}</Text>
      </TouchableOpacity>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={segStyles.imageRow}>
        {segment.map((img, i) => (
          <ImageCard key={`${i}-${img.imagePath}`} image={img} deviceId={deviceId} size={100} />
        ))}
      </ScrollView>
    </View>
  );
};

// ── Main screen ───────────────────────────────────────────────────────────────
const SearchScreen = () => {
  const dispatch = useAppDispatch();
  const deviceId = useAppSelector(s => s.auth.deviceId);
  const searchQuery = useAppSelector(s => s.search.query);
  const searchHistory = useAppSelector(s => s.search.history);

  const [textQuery, setTextQuery] = useState(searchQuery.text ?? '');
  const [results, setResults] = useState<ImageObject[][]>([]);
  const [displayCount, setDisplayCount] = useState(SEG_PAGE);
  const [loading, setLoading] = useState(false);
  const [sortBy, setSortBy] = useState<'relevance' | 'time'>('relevance');
  const [filterTab, setFilterTab] = useState<'time' | 'day' | 'month' | null>(null);
  const [summaryText, setSummaryText] = useState('');
  const [topLocations, setTopLocations] = useState<LocationSummaryItem[]>([]);
  const [topCountries, setTopCountries] = useState<CountItem[]>([]);
  const [topPeople, setTopPeople] = useState<CountItem[]>([]);
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [showMap, setShowMap] = useState(false);
  const [allDates, setAllDates] = useState<string[]>([]);

  // Activity edit modal
  const [editingSegment, setEditingSegment] = useState<ImageObject[] | null>(null);
  const [editActivity, setEditActivity] = useState('');
  const [savingActivity, setSavingActivity] = useState(false);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // Persist history to AsyncStorage whenever it changes
  useEffect(() => {
    AsyncStorage.setItem('searchHistory', JSON.stringify(searchHistory)).catch(() => {});
  }, [searchHistory]);

  useEffect(() => {
    if (!deviceId) { return; }
    getAllDates(deviceId)
      .then(res => setAllDates(res.data as string[]))
      .catch(() => {});
  }, [deviceId]);

  useEffect(() => {
    if (!textQuery.trim()) { return; }
    if (debounceRef.current) { clearTimeout(debounceRef.current); }
    debounceRef.current = setTimeout(() => {
      parseQueryFilters(textQuery, deviceId)
        .then(res => dispatch(setSearchQuery(res.data)))
        .catch(() => {});
    }, 800);
  }, [textQuery]);

  const triggerSearch = useCallback(async () => {
    Keyboard.dismiss();
    const full: SearchQuery = { ...searchQuery, text: textQuery };
    dispatch(pushToHistory(full));
    dispatch(setSearchQuery({ text: textQuery }));
    setLoading(true);
    setDisplayCount(SEG_PAGE);
    try {
      const res = await searchImages(deviceId, full, sortBy);
      const { segments, topLocations: locs, topCountries: ctrs, topPeople: ppl } = res.data;
      const ordered = sortBy === 'relevance' ? [...segments].reverse() : segments;
      setResults(ordered);
      setTopLocations(locs ?? []);
      setTopCountries(ctrs ?? []);
      setTopPeople(ppl ?? []);
      const total = ordered.reduce((s, seg) => s + seg.length, 0);
      setSummaryText(`${ordered.length} events · ${total} photos`);
    } catch {}
    finally { setLoading(false); }
  }, [searchQuery, textQuery, deviceId, sortBy]);

  const restoreHistory = (entry: SearchQuery) => {
    setTextQuery(entry.text ?? '');
    dispatch(setSearchQuery(entry));
  };

  const appendToQuery = useCallback((text: string) => {
    setTextQuery(prev => (prev.trim() ? `${prev.trim()} ${text}` : text));
  }, []);

  const toggleFilter = (field: keyof SearchQuery, value: string) => {
    const current = (searchQuery[field] as string[]) ?? [];
    const next = current.includes(value) ? current.filter(v => v !== value) : [...current, value];
    dispatch(setSearchQuery({ [field]: next } as any));
  };

  const openEditActivity = (segment: ImageObject[]) => {
    setEditingSegment(segment);
    setEditActivity(segment[0]?.description ?? '');
  };

  const handleSaveActivity = async () => {
    if (!editingSegment || !deviceId) { return; }
    const first = editingSegment[0];
    const segDate = first.date ?? first.timestamp.slice(0, 10);
    const segId = Number(first.segmentId ?? 0);
    setSavingActivity(true);
    try {
      await changeSegmentActivity(deviceId, segDate, segId, editActivity.trim());
      // Update local results
      setResults(prev => prev.map(seg =>
        seg[0]?.segmentId === first.segmentId
          ? seg.map(img => ({ ...img, description: editActivity.trim() }))
          : seg,
      ));
      setEditingSegment(null);
    } catch {
      // still close — backend may have accepted
      setEditingSegment(null);
    } finally {
      setSavingActivity(false);
    }
  };

  const pagedSegments = results.slice(0, displayCount);

  return (
    <View style={styles.container}>
      {/* Search bar */}
      <View style={styles.searchBar}>
        <TextInput
          style={styles.searchInput}
          value={textQuery}
          onChangeText={setTextQuery}
          placeholder="Search your lifelog…"
          placeholderTextColor={COLORS.textSecondary}
          multiline={false}
          returnKeyType="search"
          onSubmitEditing={triggerSearch}
        />
        <TouchableOpacity style={styles.searchBtn} onPress={triggerSearch} disabled={loading}>
          <Text style={styles.searchBtnText}>{loading ? '…' : 'Go'}</Text>
        </TouchableOpacity>
      </View>

      {/* Sort + summary */}
      <View style={styles.sortRow}>
        {(['relevance', 'time'] as const).map(s => (
          <FilterChip key={s} label={s === 'relevance' ? 'By Relevance' : 'By Time'} active={sortBy === s} onPress={() => setSortBy(s)} />
        ))}
        <View style={{ flex: 1 }} />
        {summaryText ? <Text style={styles.summary}>{summaryText}</Text> : null}
      </View>

      {/* Filter tabs */}
      <View style={styles.filterTabRow}>
        {(['time', 'day', 'month'] as const).map(tab => (
          <TouchableOpacity
            key={tab}
            style={[styles.filterTab, filterTab === tab && styles.filterTabActive]}
            onPress={() => { setFilterTab(prev => prev === tab ? null : tab); setShowHeatmap(false); setShowMap(false); }}
          >
            <Text style={[styles.filterTabText, filterTab === tab && styles.filterTabTextActive]}>
              {tab === 'time' ? 'Time of Day' : tab === 'day' ? 'Day of Week' : 'Month'}
            </Text>
          </TouchableOpacity>
        ))}
        <TouchableOpacity
          style={[styles.filterTab, showHeatmap && styles.filterTabActive]}
          onPress={() => { setShowHeatmap(p => !p); setFilterTab(null); setShowMap(false); }}
        >
          <Text style={[styles.filterTabText, showHeatmap && styles.filterTabTextActive]}>Heatmap</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.filterTab, showMap && styles.filterTabActive]}
          onPress={() => { setShowMap(p => !p); setFilterTab(null); setShowHeatmap(false); }}
        >
          <Text style={[styles.filterTabText, showMap && styles.filterTabTextActive]}>
            {searchQuery.bounds ? '📍 Map ✓' : '🗺 Map'}
          </Text>
        </TouchableOpacity>
      </View>

      {/* Filter chips */}
      {filterTab && !showHeatmap && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.filterPanel} contentContainerStyle={styles.filterPanelContent}>
          {(filterTab === 'time' ? TIME_OF_DAY_OPTIONS : filterTab === 'day' ? DAY_OF_WEEK_OPTIONS : MONTH_OPTIONS).map(opt => (
            <FilterChip
              key={opt} label={opt}
              active={(filterTab === 'time' ? searchQuery.timeOfDays : filterTab === 'day' ? searchQuery.dayOfWeeks : searchQuery.months).includes(opt)}
              onPress={() => toggleFilter(filterTab === 'time' ? 'timeOfDays' : filterTab === 'day' ? 'dayOfWeeks' : 'months', opt)}
            />
          ))}
        </ScrollView>
      )}

      {showHeatmap && <TimeHeatmap dates={allDates} />}

      {showMap && (
        <View style={styles.mapPanel}>
          <WebView
            source={{ html: MAP_HTML }}
            style={styles.mapWebView}
            javaScriptEnabled domStorageEnabled originWhitelist={['*']} mixedContentMode="always"
            onMessage={e => {
              try {
                const msg = JSON.parse(e.nativeEvent.data);
                if (msg.type === 'bounds') { dispatch(setSearchQuery({ bounds: msg.bounds as [number, number, number, number] })); }
                else if (msg.type === 'clear') { dispatch(setSearchQuery({ bounds: null })); }
              } catch {}
            }}
          />
        </View>
      )}

      {/* History */}
      {results.length === 0 && searchHistory.length > 0 && !loading && (
        <View style={styles.historySection}>
          <View style={styles.historyHeader}>
            <Text style={styles.historyTitle}>Recent Searches</Text>
            <TouchableOpacity onPress={() => dispatch(clearHistory())}>
              <Text style={styles.clearText}>Clear</Text>
            </TouchableOpacity>
          </View>
          {searchHistory.slice(0, 8).map((entry, i) => {
            const filterCount = [
              entry.timeOfDays?.length, entry.dayOfWeeks?.length, entry.months?.length,
              entry.years?.length, entry.locationIds?.length, entry.peopleIds?.length,
            ].reduce((sum, n) => sum + (n ?? 0), 0);
            return (
              <View key={i} style={styles.historyRow}>
                <TouchableOpacity style={styles.historyItem} onPress={() => restoreHistory(entry)}>
                  <Text style={styles.historyIcon}>🕐</Text>
                  <Text style={styles.historyText} numberOfLines={1}>{entry.text || '(filters only)'}</Text>
                  {filterCount > 0 && <Text style={styles.filterBadge}>+{filterCount}</Text>}
                </TouchableOpacity>
                <TouchableOpacity onPress={() => dispatch(removeFromHistory(i))} style={styles.removeBtn}>
                  <Text style={styles.removeText}>✕</Text>
                </TouchableOpacity>
              </View>
            );
          })}
        </View>
      )}

      {/* Results */}
      {loading ? (
        <ActivityIndicator style={{ marginTop: 40 }} color={COLORS.primary} size="large" />
      ) : (
        <FlatList
          data={pagedSegments}
          keyExtractor={(_, i) => String(i)}
          contentContainerStyle={styles.grid}
          ListHeaderComponent={
            results.length > 0 ? (
              <ResultSummaryBar
                results={results}
                topLocations={topLocations}
                topCountries={topCountries}
                topPeople={topPeople}
                onAppendToQuery={appendToQuery}
              />
            ) : null
          }
          renderItem={({ item: seg }) => (
            <SegmentGroup segment={seg} deviceId={deviceId} onEditActivity={openEditActivity} />
          )}
          onEndReached={() => setDisplayCount(c => Math.min(c + SEG_PAGE, results.length))}
          onEndReachedThreshold={0.4}
          ListFooterComponent={
            displayCount < results.length ? (
              <ActivityIndicator color={COLORS.primary} style={{ marginVertical: 16 }} />
            ) : null
          }
          ListEmptyComponent={
            results.length === 0 ? null : (
              <View style={styles.empty}><Text style={styles.emptyText}>No results</Text></View>
            )
          }
        />
      )}

      {/* Activity edit modal */}
      <Modal visible={!!editingSegment} transparent animationType="slide" onRequestClose={() => setEditingSegment(null)}>
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Edit Activity</Text>
            {editingSegment && (
              <Text style={styles.modalSub}>
                {formatTimeTz(editingSegment[0].timestamp, editingSegment[0].timezone || config.defaultTimezone)}
              </Text>
            )}
            <TextInput
              style={styles.modalInput}
              value={editActivity}
              onChangeText={setEditActivity}
              placeholder="e.g. Walking in the park"
              placeholderTextColor={COLORS.textSecondary}
              autoFocus
              returnKeyType="done"
              onSubmitEditing={handleSaveActivity}
            />
            <View style={styles.modalBtns}>
              <TouchableOpacity style={styles.cancelBtn} onPress={() => setEditingSegment(null)}>
                <Text style={styles.cancelBtnText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.saveBtn, savingActivity && styles.saveBtnDisabled]}
                onPress={handleSaveActivity}
                disabled={savingActivity}
              >
                {savingActivity
                  ? <ActivityIndicator size="small" color="#fff" />
                  : <Text style={styles.saveBtnText}>Save</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
};

const segStyles = StyleSheet.create({
  container: {
    marginBottom: 4, backgroundColor: COLORS.surface,
    borderRadius: 12, overflow: 'hidden', marginHorizontal: 6, elevation: 1,
  },
  header: { paddingHorizontal: 12, paddingVertical: 8 },
  time: { fontSize: 11, fontWeight: '700', color: COLORS.primary, marginBottom: 2 },
  activity: { fontSize: 13, color: COLORS.textPrimary, lineHeight: 18 },
  noActivity: { fontSize: 12, color: COLORS.textSecondary, fontStyle: 'italic' },
  count: { fontSize: 10, color: COLORS.textSecondary, marginTop: 3 },
  imageRow: { paddingHorizontal: 6, paddingBottom: 8, gap: 2 },
});

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.background },
  searchBar: {
    flexDirection: 'row', alignItems: 'center', margin: 10,
    backgroundColor: COLORS.surface, borderRadius: 12, borderWidth: 1, borderColor: COLORS.divider,
    overflow: 'hidden',
  },
  searchInput: { flex: 1, paddingHorizontal: 14, paddingVertical: 10, fontSize: 14, color: COLORS.textPrimary },
  searchBtn: { backgroundColor: COLORS.secondary, paddingHorizontal: 18, paddingVertical: 12 },
  searchBtnText: { color: '#fff', fontWeight: '700', fontSize: 14 },
  sortRow: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 10, paddingBottom: 4, gap: 6 },
  summary: { fontSize: 11, color: COLORS.textSecondary },
  filterTabRow: { flexDirection: 'row', paddingHorizontal: 10, gap: 6, paddingBottom: 6, flexWrap: 'wrap' },
  filterTab: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 8, borderWidth: 1, borderColor: COLORS.divider },
  filterTabActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  filterTabText: { fontSize: 11, color: COLORS.textSecondary },
  filterTabTextActive: { color: '#fff', fontWeight: '600' },
  filterPanel: { maxHeight: 44, borderTopWidth: 1, borderColor: COLORS.divider },
  filterPanelContent: { paddingHorizontal: 10, paddingVertical: 6, gap: 6 },
  filterChip: {
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: 14,
    borderWidth: 1, borderColor: COLORS.divider, backgroundColor: COLORS.background,
  },
  filterChipActive: { backgroundColor: COLORS.secondary, borderColor: COLORS.secondary },
  filterChipText: { fontSize: 12, color: COLORS.textSecondary },
  filterChipTextActive: { color: '#fff', fontWeight: '600' },
  mapPanel: { height: 280, borderTopWidth: 1, borderColor: COLORS.divider },
  mapWebView: { flex: 1 },
  historySection: { paddingHorizontal: 12, paddingVertical: 8 },
  historyHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 },
  historyTitle: { fontSize: 12, color: COLORS.textSecondary, fontWeight: '600' },
  clearText: { fontSize: 11, color: COLORS.primary },
  historyRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 5 },
  historyItem: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 6 },
  historyIcon: { fontSize: 12 },
  historyText: { flex: 1, fontSize: 13, color: COLORS.textPrimary },
  filterBadge: { fontSize: 11, color: COLORS.secondary, fontWeight: '600' },
  removeBtn: { padding: 6 },
  removeText: { fontSize: 12, color: COLORS.textSecondary },
  grid: { paddingTop: 6, paddingBottom: 24 },
  empty: { padding: 40, alignItems: 'center' },
  emptyText: { color: COLORS.textSecondary, fontSize: 14 },
  // Activity edit modal
  modalOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'flex-end' },
  modalCard: {
    backgroundColor: COLORS.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20,
    padding: 20, paddingBottom: 34, gap: 10,
  },
  modalTitle: { fontSize: 16, fontWeight: '700', color: COLORS.textPrimary },
  modalSub: { fontSize: 12, color: COLORS.textSecondary, marginTop: -4 },
  modalInput: {
    borderWidth: 1, borderColor: COLORS.divider, borderRadius: 10,
    paddingHorizontal: 14, paddingVertical: 10, fontSize: 14, color: COLORS.textPrimary,
  },
  modalBtns: { flexDirection: 'row', gap: 10 },
  cancelBtn: {
    flex: 1, paddingVertical: 12, borderRadius: 10,
    borderWidth: 1, borderColor: COLORS.divider, alignItems: 'center',
  },
  cancelBtnText: { fontSize: 14, color: COLORS.textSecondary, fontWeight: '600' },
  saveBtn: { flex: 1, paddingVertical: 12, borderRadius: 10, backgroundColor: COLORS.secondary, alignItems: 'center' },
  saveBtnDisabled: { opacity: 0.45 },
  saveBtnText: { color: '#fff', fontWeight: '700', fontSize: 14 },
});

export default SearchScreen;

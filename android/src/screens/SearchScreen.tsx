import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  ActivityIndicator,
  Dimensions,
  FlatList,
  Image,
  Keyboard,
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
import customParseFormat from 'dayjs/plugin/customParseFormat';
import {
  getAllDates,
  getAllFaces,
  getAvailableValues,
  parseQueryFilters,
  searchImages,
} from '../api/browsing';
import {
  getLocations,
  getMovingPeriods,
  searchLocations,
} from '../api/searchFilters';
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
import { COLORS } from '../constants';
import { CountItem, ImageObject, LocationData, LocationSummaryItem, SearchQuery } from '../types';

dayjs.extend(utc);
dayjs.extend(timezone);
dayjs.extend(customParseFormat);

const IMG_PAGE = 60;
const COLS = 3;
const IMG_SIZE = Math.floor((Dimensions.get('window').width - (COLS + 1) * 2) / COLS);
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
const SEASON_OPTIONS = ['spring', 'summer', 'autumn', 'winter'];
const MONTH_OPTIONS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

type FilterTab = 'time' | 'day' | 'season' | 'month' | 'year' | 'date' | 'location' | 'people';

const DATE_FORMATS = ['D MMM YYYY', 'D MMMM YYYY', 'YYYY-MM-DD', 'DD/MM/YYYY', 'D/M/YYYY'];

const parseDate = (text: string): dayjs.Dayjs | null => {
  for (const fmt of DATE_FORMATS) {
    const d = dayjs(text.trim(), fmt, true);
    if (d.isValid()) return d;
  }
  const d = dayjs(text.trim());
  return d.isValid() ? d : null;
};

const FilterChip = ({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) => (
  <TouchableOpacity style={[styles.filterChip, active && styles.filterChipActive]} onPress={onPress}>
    <Text style={[styles.filterChipText, active && styles.filterChipTextActive]}>
      {label.charAt(0).toUpperCase() + label.slice(1)}
    </Text>
  </TouchableOpacity>
);


// ── Main screen ───────────────────────────────────────────────────────────────
const SearchScreen = () => {
  const dispatch = useAppDispatch();
  const deviceId = useAppSelector(s => s.auth.deviceId);
  const searchQuery = useAppSelector(s => s.search.query);
  const searchHistory = useAppSelector(s => s.search.history);

  const [textQuery, setTextQuery] = useState(searchQuery.text ?? '');
  const [segments, setSegments] = useState<ImageObject[][]>([]);
  const [displayCount, setDisplayCount] = useState(IMG_PAGE);
  const [loading, setLoading] = useState(false);
  const [sortBy, setSortBy] = useState<'relevance' | 'time'>('relevance');
  const [filterTab, setFilterTab] = useState<FilterTab | null>(null);
  const [summaryText, setSummaryText] = useState('');
  const [topLocations, setTopLocations] = useState<LocationSummaryItem[]>([]);
  const [topCountries, setTopCountries] = useState<CountItem[]>([]);
  const [topPeople, setTopPeople] = useState<CountItem[]>([]);
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [showMap, setShowMap] = useState(false);
  const [allDates, setAllDates] = useState<string[]>([]);

  // New filter state
  const [startDateText, setStartDateText] = useState('');
  const [endDateText, setEndDateText] = useState('');
  const [availableYears, setAvailableYears] = useState<number[]>([]);
  const [availableCountries, setAvailableCountries] = useState<string[]>([]);
  const [availableLocations, setAvailableLocations] = useState<LocationData[]>([]);
  const [locationSearch, setLocationSearch] = useState('');
  const [searchedLocations, setSearchedLocations] = useState<LocationData[]>([]);
  const [availableFaces, setAvailableFaces] = useState<{ name: string; images: string[]; id: string }[]>([]);

  const allImages = useMemo(() => segments.flat(), [segments]);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const locationSearchDebounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // Persist history to AsyncStorage whenever it changes
  useEffect(() => {
    AsyncStorage.setItem('searchHistory', JSON.stringify(searchHistory)).catch(() => {});
  }, [searchHistory]);

  useEffect(() => {
    if (!deviceId) return;
    getAllDates(deviceId)
      .then(res => setAllDates(res.data as string[]))
      .catch(() => {});
  }, [deviceId]);

  // Parse query filters on text change
  useEffect(() => {
    if (!textQuery.trim()) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      parseQueryFilters(textQuery, deviceId)
        .then(res => dispatch(setSearchQuery(res.data)))
        .catch(() => {});
    }, 800);
  }, [textQuery]);

  // Load available years
  useEffect(() => {
    if (!deviceId) return;
    getAvailableValues(deviceId, 'year')
      .then(res => setAvailableYears((res.data as string[]).map(Number).filter(n => !isNaN(n)).sort((a, b) => b - a)))
      .catch(() => {});
  }, [deviceId]);

  // Load available countries (changes when isMoving changes)
  useEffect(() => {
    if (!deviceId) return;
    const field = searchQuery.isMoving ? 'moving-cross-country' : 'country';
    getAvailableValues(deviceId, field)
      .then(res => setAvailableCountries(res.data as string[]))
      .catch(() => {});
  }, [deviceId, searchQuery.isMoving]);

  // Load available locations (changes when countries or isMoving change)
  useEffect(() => {
    if (!deviceId) return;
    const countries = searchQuery.countries ?? [];
    const apiCall = searchQuery.isMoving
      ? getMovingPeriods(deviceId, countries)
      : getLocations(deviceId, countries);
    apiCall
      .then(res => setAvailableLocations(res.data))
      .catch(() => {});
  }, [deviceId, (searchQuery.countries ?? []).join(','), searchQuery.isMoving]);

  // Load faces for people filter
  useEffect(() => {
    if (!deviceId) return;
    getAllFaces(deviceId)
      .then(res => setAvailableFaces(res.data))
      .catch(() => {});
  }, [deviceId]);

  // Debounced location search
  useEffect(() => {
    if (!deviceId || locationSearch.trim().length < 2) {
      setSearchedLocations([]);
      return;
    }
    if (locationSearchDebounceRef.current) clearTimeout(locationSearchDebounceRef.current);
    locationSearchDebounceRef.current = setTimeout(() => {
      searchLocations(deviceId, locationSearch)
        .then(res => setSearchedLocations(res.data))
        .catch(() => {});
    }, 300);
  }, [locationSearch, deviceId]);

  const triggerSearch = useCallback(async (sortOverride?: 'relevance' | 'time') => {
    Keyboard.dismiss();
    const effectiveSort = sortOverride ?? sortBy;
    const full: SearchQuery = { ...searchQuery, text: textQuery };
    dispatch(pushToHistory(full));
    dispatch(setSearchQuery({ text: textQuery }));
    setLoading(true);
    setDisplayCount(IMG_PAGE);
    try {
      const res = await searchImages(deviceId, full, effectiveSort);
      const { segments: segs, topLocations: locs, topCountries: ctrs, topPeople: ppl } = res.data;
      const ordered = effectiveSort === 'relevance' ? [...segs].reverse() : segs;
      setSegments(ordered);
      setTopLocations(locs ?? []);
      setTopCountries(ctrs ?? []);
      setTopPeople(ppl ?? []);
      const total = ordered.reduce((s, seg) => s + seg.length, 0);
      setSummaryText(`${total} photos · ${ordered.length} events`);
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

  const toggleYear = (year: number) => {
    const current = searchQuery.years ?? [];
    const next = current.includes(year) ? current.filter(y => y !== year) : [...current, year];
    dispatch(setSearchQuery({ years: next }));
  };

  const toggleCountry = (country: string) => {
    const current = searchQuery.countries ?? [];
    const isRemoving = current.includes(country);
    const next = isRemoving ? current.filter(c => c !== country) : [...current, country];
    // Clear locationIds when countries change
    dispatch(setSearchQuery({ countries: next, locationIds: isRemoving ? searchQuery.locationIds : [] }));
  };

  const toggleLocation = (id: string) => {
    const current = searchQuery.locationIds ?? [];
    const next = current.includes(id) ? current.filter(l => l !== id) : [...current, id];
    dispatch(setSearchQuery({ locationIds: next }));
  };

  const toggleFace = (id: string) => {
    const current = searchQuery.peopleIds ?? [];
    const next = current.includes(id) ? current.filter(p => p !== id) : [...current, id];
    dispatch(setSearchQuery({ peopleIds: next }));
  };

  const handleAddDateRange = () => {
    const start = parseDate(startDateText);
    if (!start) return;
    const end = endDateText.trim() ? (parseDate(endDateText) ?? start) : start;
    const startStr = start.format('YYYY-MM-DD');
    const endStr = end.format('YYYY-MM-DD');
    const current = searchQuery.customRanges ?? [];
    if (current.some(r => r.start === startStr && r.end === endStr)) return;
    dispatch(setSearchQuery({ customRanges: [...current, { start: startStr, end: endStr }] }));
    setStartDateText('');
    setEndDateText('');
  };

  const setFilterTabAndClear = (tab: FilterTab | null) => {
    setFilterTab(prev => prev === tab ? null : tab);
    setShowHeatmap(false);
    setShowMap(false);
  };

  // ── Filter panel renderers ──────────────────────────────────────────────────

  const renderChipsPanel = (options: string[], selected: string[], onToggle: (v: string) => void) => (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.filterPanel} contentContainerStyle={styles.filterPanelContent}>
      {options.map(opt => (
        <FilterChip
          key={opt}
          label={opt}
          active={selected.includes(opt)}
          onPress={() => onToggle(opt)}
        />
      ))}
    </ScrollView>
  );

  const renderDatePanel = () => (
    <View style={styles.datePanel}>
      <View style={styles.dateInputRow}>
        <TextInput
          style={[styles.dateInput, startDateText && !parseDate(startDateText) ? styles.dateInputError : null]}
          placeholder="Start: 15 Jun 2024"
          placeholderTextColor={COLORS.textSecondary}
          value={startDateText}
          onChangeText={setStartDateText}
          onSubmitEditing={handleAddDateRange}
          returnKeyType="next"
        />
        <TextInput
          style={[styles.dateInput, endDateText && !parseDate(endDateText) ? styles.dateInputError : null]}
          placeholder="End (optional)"
          placeholderTextColor={COLORS.textSecondary}
          value={endDateText}
          onChangeText={setEndDateText}
          onSubmitEditing={handleAddDateRange}
          returnKeyType="done"
        />
        <TouchableOpacity
          style={[styles.addDateBtn, (!startDateText || !parseDate(startDateText)) && styles.addDateBtnDisabled]}
          onPress={handleAddDateRange}
          disabled={!startDateText || !parseDate(startDateText)}
        >
          <Text style={styles.addDateBtnText}>Add</Text>
        </TouchableOpacity>
      </View>
      {(searchQuery.customRanges ?? []).length > 0 && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filterPanelContent}>
          {(searchQuery.customRanges ?? []).map((r, i) => {
            const label = r.start === r.end
              ? dayjs(r.start).format('D MMM YYYY')
              : `${dayjs(r.start).format('D MMM')} – ${dayjs(r.end).format('D MMM YYYY')}`;
            return (
              <View key={i} style={styles.dateRangeChip}>
                <Text style={styles.dateRangeChipText}>{label}</Text>
                <TouchableOpacity onPress={() => {
                  const filtered = (searchQuery.customRanges ?? []).filter((_, idx) => idx !== i);
                  dispatch(setSearchQuery({ customRanges: filtered }));
                }}>
                  <Text style={styles.dateRangeChipRemove}>✕</Text>
                </TouchableOpacity>
              </View>
            );
          })}
        </ScrollView>
      )}
    </View>
  );

  const renderLocationPanel = () => {
    const displayedLocations = locationSearch.trim().length >= 2 ? searchedLocations : availableLocations;
    const selectedLocationIds = searchQuery.locationIds ?? [];
    const selectedCountries = searchQuery.countries ?? [];

    return (
      <ScrollView style={styles.locationPanel} contentContainerStyle={styles.locationPanelContent} keyboardShouldPersistTaps="handled">
        {/* isMoving toggle */}
        <View style={styles.locationRow}>
          <Text style={styles.locationSectionLabel}>On the Move</Text>
          <TouchableOpacity
            style={[styles.toggleChip, searchQuery.isMoving && styles.toggleChipActive]}
            onPress={() => dispatch(setSearchQuery({ isMoving: !searchQuery.isMoving, countries: [], locationIds: [] }))}
          >
            <Text style={[styles.toggleChipText, searchQuery.isMoving && styles.toggleChipTextActive]}>
              {searchQuery.isMoving ? 'On ✓' : 'Off'}
            </Text>
          </TouchableOpacity>
        </View>

        {/* Countries */}
        {availableCountries.length > 0 && (
          <View>
            <Text style={styles.locationSectionLabel}>Countries</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filterPanelContent}>
              {availableCountries.map(c => (
                <FilterChip
                  key={c}
                  label={c}
                  active={selectedCountries.includes(c)}
                  onPress={() => toggleCountry(c)}
                />
              ))}
            </ScrollView>
          </View>
        )}

        {/* Location search */}
        <TextInput
          style={styles.locationSearchInput}
          placeholder="Search places…"
          placeholderTextColor={COLORS.textSecondary}
          value={locationSearch}
          onChangeText={setLocationSearch}
          returnKeyType="search"
        />

        {/* Locations list */}
        {displayedLocations.length > 0 && (
          <View>
            <Text style={styles.locationSectionLabel}>Places</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filterPanelContent}>
              {displayedLocations.map(loc => {
                const id = loc.id ?? '';
                if (!id) return null;
                const parts = [loc.suburb && loc.suburb !== loc.city ? loc.suburb : null, loc.city, loc.country].filter(Boolean);
                const subtitle = parts.join(', ');
                const isActive = selectedLocationIds.includes(id);
                return (
                  <TouchableOpacity
                    key={id}
                    style={[styles.locationChip, isActive && styles.locationChipActive]}
                    onPress={() => toggleLocation(id)}
                  >
                    <Text style={[styles.locationChipName, isActive && styles.locationChipNameActive]} numberOfLines={1}>
                      {loc.name ?? id}
                    </Text>
                    {subtitle ? (
                      <Text style={[styles.locationChipSub, isActive && styles.locationChipSubActive]} numberOfLines={1}>
                        {subtitle}
                      </Text>
                    ) : null}
                    {loc.count != null ? (
                      <Text style={[styles.locationChipSub, isActive && styles.locationChipSubActive]}>
                        {loc.count} visits
                      </Text>
                    ) : null}
                  </TouchableOpacity>
                );
              })}
            </ScrollView>
          </View>
        )}

        {/* Active location chips */}
        {selectedLocationIds.length > 0 && displayedLocations.length === 0 && (
          <View>
            <Text style={styles.locationSectionLabel}>Selected</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filterPanelContent}>
              {selectedLocationIds.map(id => (
                <FilterChip
                  key={id}
                  label={id}
                  active
                  onPress={() => toggleLocation(id)}
                />
              ))}
            </ScrollView>
          </View>
        )}
      </ScrollView>
    );
  };

  const renderPeoplePanel = () => (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.filterPanel} contentContainerStyle={styles.peoplePanelContent}>
      {availableFaces.length === 0 ? (
        <View style={styles.emptyPeopleHint}>
          <Text style={styles.emptyPeopleText}>No known people</Text>
        </View>
      ) : (
        availableFaces.map(face => {
          const isSelected = (searchQuery.peopleIds ?? []).includes(face.id);
          return (
            <TouchableOpacity
              key={face.id}
              style={[styles.faceChip, isSelected && styles.faceChipActive]}
              onPress={() => toggleFace(face.id)}
            >
              {face.images[0] ? (
                <Image source={{ uri: face.images[0] }} style={styles.faceAvatar} />
              ) : (
                <View style={[styles.faceAvatar, styles.faceAvatarPlaceholder]}>
                  <Text style={{ fontSize: 16 }}>👤</Text>
                </View>
              )}
              <Text style={[styles.faceChipText, isSelected && styles.faceChipTextActive]} numberOfLines={1}>
                {face.name}
              </Text>
            </TouchableOpacity>
          );
        })
      )}
    </ScrollView>
  );

  const renderFilterPanel = () => {
    if (!filterTab || showHeatmap) return null;
    switch (filterTab) {
      case 'time':
        return renderChipsPanel(TIME_OF_DAY_OPTIONS, searchQuery.timeOfDays ?? [], v => toggleFilter('timeOfDays', v));
      case 'day':
        return renderChipsPanel(DAY_OF_WEEK_OPTIONS, searchQuery.dayOfWeeks ?? [], v => toggleFilter('dayOfWeeks', v));
      case 'season':
        return renderChipsPanel(SEASON_OPTIONS, searchQuery.seasons ?? [], v => toggleFilter('seasons', v));
      case 'month':
        return renderChipsPanel(MONTH_OPTIONS, searchQuery.months ?? [], v => toggleFilter('months', v));
      case 'year':
        return renderChipsPanel(
          availableYears.map(String),
          (searchQuery.years ?? []).map(String),
          v => toggleYear(Number(v)),
        );
      case 'date':
        return renderDatePanel();
      case 'location':
        return renderLocationPanel();
      case 'people':
        return renderPeoplePanel();
    }
  };

  // ── Active filter label helpers ─────────────────────────────────────────────

  const tabLabel = (tab: FilterTab) => {
    const check = (count: number) => count > 0 ? ` (${count})` : '';
    switch (tab) {
      case 'time':   return `Time${check((searchQuery.timeOfDays ?? []).length)}`;
      case 'day':    return `Day${check((searchQuery.dayOfWeeks ?? []).length)}`;
      case 'season': return `Season${check((searchQuery.seasons ?? []).length)}`;
      case 'month':  return `Month${check((searchQuery.months ?? []).length)}`;
      case 'year':   return `Year${check((searchQuery.years ?? []).length)}`;
      case 'date': {
        const n = (searchQuery.customRanges ?? []).length;
        return `Date${n > 0 ? ` (${n})` : ''}`;
      }
      case 'location': {
        const n = (searchQuery.countries ?? []).length + (searchQuery.locationIds ?? []).length + (searchQuery.isMoving ? 1 : 0);
        return `Location${n > 0 ? ` (${n})` : ''}`;
      }
      case 'people':
        return `People${check((searchQuery.peopleIds ?? []).length)}`;
    }
  };

  const isTabActive = (tab: FilterTab) => {
    switch (tab) {
      case 'time':     return (searchQuery.timeOfDays ?? []).length > 0;
      case 'day':      return (searchQuery.dayOfWeeks ?? []).length > 0;
      case 'season':   return (searchQuery.seasons ?? []).length > 0;
      case 'month':    return (searchQuery.months ?? []).length > 0;
      case 'year':     return (searchQuery.years ?? []).length > 0;
      case 'date':     return (searchQuery.customRanges ?? []).length > 0;
      case 'location': return (searchQuery.countries ?? []).length > 0 || (searchQuery.locationIds ?? []).length > 0 || !!searchQuery.isMoving;
      case 'people':   return (searchQuery.peopleIds ?? []).length > 0;
    }
  };

  const pagedImages = allImages.slice(0, displayCount);
  const FILTER_TABS: FilterTab[] = ['time', 'day', 'season', 'month', 'year', 'date', 'location', 'people'];

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
          onSubmitEditing={() => triggerSearch()}
        />
        <TouchableOpacity style={styles.searchBtn} onPress={() => triggerSearch()} disabled={loading}>
          <Text style={styles.searchBtnText}>{loading ? '…' : 'Go'}</Text>
        </TouchableOpacity>
      </View>

      {/* Sort + summary */}
      <View style={styles.sortRow}>
        {(['relevance', 'time'] as const).map(s => (
          <FilterChip
            key={s}
            label={s === 'relevance' ? 'By Relevance' : 'By Time'}
            active={sortBy === s}
            onPress={() => {
              setSortBy(s);
              if (allImages.length > 0) triggerSearch(s);
            }}
          />
        ))}
        <View style={{ flex: 1 }} />
        {summaryText ? <Text style={styles.summary}>{summaryText}</Text> : null}
      </View>

      {/* Filter tabs */}
      <View style={styles.filterTabRow}>
        {FILTER_TABS.map(tab => (
          <TouchableOpacity
            key={tab}
            style={[
              styles.filterTab,
              (filterTab === tab || isTabActive(tab)) && styles.filterTabActive,
            ]}
            onPress={() => setFilterTabAndClear(tab)}
          >
            <Text style={[
              styles.filterTabText,
              (filterTab === tab || isTabActive(tab)) && styles.filterTabTextActive,
            ]}>
              {tabLabel(tab)}
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

      {/* Filter panels */}
      {renderFilterPanel()}

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
      {allImages.length === 0 && searchHistory.length > 0 && !loading && (
        <View style={styles.historySection}>
          <View style={styles.historyHeader}>
            <Text style={styles.historyTitle}>Recent Searches</Text>
            <TouchableOpacity onPress={() => dispatch(clearHistory())}>
              <Text style={styles.clearText}>Clear</Text>
            </TouchableOpacity>
          </View>
          {searchHistory.slice(0, 8).map((entry, i) => {
            const filterCount = [
              entry.timeOfDays?.length, entry.dayOfWeeks?.length, entry.seasons?.length,
              entry.months?.length, entry.years?.length, entry.customRanges?.length,
              entry.countries?.length, entry.locationIds?.length, entry.peopleIds?.length,
              entry.isMoving ? 1 : 0,
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
          data={pagedImages}
          keyExtractor={(img, i) => `${i}-${img.imagePath}`}
          numColumns={COLS}
          columnWrapperStyle={styles.gridRow}
          contentContainerStyle={styles.grid}
          ListHeaderComponent={
            segments.length > 0 ? (
              <ResultSummaryBar
                results={segments}
                topLocations={topLocations}
                topCountries={topCountries}
                topPeople={topPeople}
                onAppendToQuery={appendToQuery}
              />
            ) : null
          }
          renderItem={({ item: img }) => (
            <ImageCard image={img} deviceId={deviceId} size={IMG_SIZE} />
          )}
          onEndReached={() => setDisplayCount(c => Math.min(c + IMG_PAGE, allImages.length))}
          onEndReachedThreshold={0.4}
          ListFooterComponent={
            displayCount < allImages.length ? (
              <ActivityIndicator color={COLORS.primary} style={{ marginVertical: 16 }} />
            ) : null
          }
          ListEmptyComponent={
            allImages.length === 0 ? null : (
              <View style={styles.empty}><Text style={styles.emptyText}>No results</Text></View>
            )
          }
        />
      )}
    </View>
  );
};


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

  // Date range panel
  datePanel: {
    borderTopWidth: 1, borderColor: COLORS.divider,
    paddingHorizontal: 10, paddingVertical: 8, gap: 6,
  },
  dateInputRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  dateInput: {
    flex: 1, height: 34, paddingHorizontal: 10, fontSize: 12,
    backgroundColor: COLORS.surface, borderRadius: 8,
    borderWidth: 1, borderColor: COLORS.divider, color: COLORS.textPrimary,
  },
  dateInputError: { borderColor: '#e74c3c' },
  addDateBtn: {
    backgroundColor: COLORS.primary, paddingHorizontal: 12, paddingVertical: 7,
    borderRadius: 8,
  },
  addDateBtnDisabled: { backgroundColor: COLORS.divider },
  addDateBtnText: { color: '#fff', fontSize: 12, fontWeight: '600' },
  dateRangeChip: {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: 14,
    backgroundColor: COLORS.secondary, borderWidth: 1, borderColor: COLORS.secondary,
  },
  dateRangeChipText: { fontSize: 11, color: '#fff', fontWeight: '600' },
  dateRangeChipRemove: { fontSize: 11, color: 'rgba(255,255,255,0.8)', marginLeft: 2 },

  // Location panel
  locationPanel: { maxHeight: 220, borderTopWidth: 1, borderColor: COLORS.divider },
  locationPanelContent: { paddingHorizontal: 10, paddingVertical: 8, gap: 8 },
  locationRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  locationSectionLabel: { fontSize: 11, fontWeight: '600', color: COLORS.textSecondary, marginBottom: 2 },
  locationSearchInput: {
    height: 34, paddingHorizontal: 10, fontSize: 12,
    backgroundColor: COLORS.surface, borderRadius: 8,
    borderWidth: 1, borderColor: COLORS.divider, color: COLORS.textPrimary,
  },
  toggleChip: {
    paddingHorizontal: 12, paddingVertical: 4, borderRadius: 14,
    borderWidth: 1, borderColor: COLORS.divider, backgroundColor: COLORS.background,
  },
  toggleChipActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  toggleChipText: { fontSize: 12, color: COLORS.textSecondary },
  toggleChipTextActive: { color: '#fff', fontWeight: '600' },
  locationChip: {
    paddingHorizontal: 10, paddingVertical: 5, borderRadius: 10,
    borderWidth: 1, borderColor: COLORS.divider, backgroundColor: COLORS.background,
    maxWidth: 150,
  },
  locationChipActive: { backgroundColor: COLORS.secondary, borderColor: COLORS.secondary },
  locationChipName: { fontSize: 12, color: COLORS.textPrimary },
  locationChipNameActive: { color: '#fff', fontWeight: '600' },
  locationChipSub: { fontSize: 10, color: COLORS.textSecondary },
  locationChipSubActive: { color: 'rgba(255,255,255,0.8)' },

  // People panel
  peoplePanelContent: { paddingHorizontal: 10, paddingVertical: 8, gap: 10, alignItems: 'center' },
  faceChip: {
    alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 6,
    borderRadius: 10, borderWidth: 1, borderColor: COLORS.divider, backgroundColor: COLORS.background,
    minWidth: 60,
  },
  faceChipActive: { backgroundColor: COLORS.secondary, borderColor: COLORS.secondary },
  faceAvatar: { width: 36, height: 36, borderRadius: 18 },
  faceAvatarPlaceholder: { backgroundColor: COLORS.surface, alignItems: 'center', justifyContent: 'center' },
  faceChipText: { fontSize: 10, color: COLORS.textPrimary, textAlign: 'center', maxWidth: 56 },
  faceChipTextActive: { color: '#fff' },
  emptyPeopleHint: { paddingVertical: 10, paddingHorizontal: 4 },
  emptyPeopleText: { fontSize: 12, color: COLORS.textSecondary },

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
  grid: { paddingTop: 4, paddingBottom: 24 },
  gridRow: { gap: 2, marginBottom: 2, paddingHorizontal: 2 },
  empty: { padding: 40, alignItems: 'center' },
  emptyText: { color: COLORS.textSecondary, fontSize: 14 },
});

export default SearchScreen;

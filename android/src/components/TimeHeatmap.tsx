import React, { useMemo, useState } from 'react';
import {
  StyleSheet,
  Text,
  TouchableOpacity,
  useWindowDimensions,
  View,
} from 'react-native';
import dayjs from 'dayjs';
import { COLORS } from '../constants';
import { useAppDispatch, useAppSelector } from '../store';
import { setSearchQuery } from '../store/slices/searchSlice';

const TIME_OF_DAY = ['morning', 'midday', 'afternoon', 'evening', 'night'];
const TOD_LABELS  = ['Morn', 'Noon', 'Aft', 'Eve', 'Night'];
const MONTHS      = ['January','February','March','April','May','June','July','August','September','October','November','December'];
const MONTH_LABELS= ['J','F','M','A','M','J','J','A','S','O','N','D'];
const DAYS        = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
const DAY_LABELS  = ['M','T','W','T','F','S','S'];

function computeDensity(dates: string[]) {
  const mc = new Array(12).fill(0);
  const dc = new Array(7).fill(0);
  for (const d of dates) {
    const dt = dayjs(d);
    mc[dt.month()]++;
    dc[(dt.day() + 6) % 7]++; // 0=Mon, 6=Sun
  }
  const maxM = Math.max(...mc, 1);
  const maxD = Math.max(...dc, 1);
  return { month: mc.map(c => c / maxM), dayOfWeek: dc.map(c => c / maxD) };
}

function cellBg(densityNorm: number, rowSel: boolean, colSel: boolean): string {
  if (rowSel && colSel) {
    const a = (densityNorm * 0.72 + 0.08).toFixed(2);
    return `rgba(22,162,153,${a})`;
  }
  return 'rgba(0,0,0,0.05)';
}

interface Props {
  dates: string[];
}

const TimeHeatmap = ({ dates }: Props) => {
  const [mode, setMode] = useState<'month' | 'week'>('month');
  const dispatch  = useAppDispatch();
  const { timeOfDays, months, dayOfWeeks } = useAppSelector(s => s.search.query);
  const { width }  = useWindowDimensions();

  const density = useMemo(() => computeDensity(dates), [dates]);

  const col = mode === 'month'
    ? { labels: MONTH_LABELS, full: MONTHS,   counts: density.month,     field: 'months' as const,     sel: months }
    : { labels: DAY_LABELS,   full: DAYS,     counts: density.dayOfWeek, field: 'dayOfWeeks' as const,  sel: dayOfWeeks };

  const HEADER_W = 46;
  const cellW    = Math.floor((width - HEADER_W - 20) / col.labels.length);
  const cellH    = 28;

  const rowSel = (tod: string) => timeOfDays.length === 0 || timeOfDays.includes(tod);
  const colSel = (val: string) => col.sel.length === 0   || col.sel.includes(val);

  const toggleRow = (tod: string) => {
    const next = timeOfDays.includes(tod)
      ? timeOfDays.filter(t => t !== tod)
      : [...timeOfDays, tod];
    dispatch(setSearchQuery({ timeOfDays: next }));
  };

  const toggleCol = (val: string) => {
    const curr = col.sel;
    const next = curr.includes(val) ? curr.filter(v => v !== val) : [...curr, val];
    dispatch(setSearchQuery({ [col.field]: next } as any));
  };

  const hasFilters = timeOfDays.length + col.sel.length > 0;

  return (
    <View style={styles.root}>
      {/* Mode tabs */}
      <View style={styles.modeRow}>
        <Text style={styles.heading}>Time Heatmap</Text>
        <View style={styles.modeTabs}>
          {(['month', 'week'] as const).map(m => (
            <TouchableOpacity
              key={m}
              style={[styles.modeTab, mode === m && styles.modeTabActive]}
              onPress={() => setMode(m)}
            >
              <Text style={[styles.modeTabText, mode === m && styles.modeTabTextActive]}>
                {m === 'month' ? 'Month' : 'Day'}
              </Text>
            </TouchableOpacity>
          ))}
        </View>
        {hasFilters && (
          <TouchableOpacity
            onPress={() => dispatch(setSearchQuery({ timeOfDays: [], months: [], dayOfWeeks: [] }))}
          >
            <Text style={styles.clearBtn}>Clear</Text>
          </TouchableOpacity>
        )}
      </View>

      {/* Column headers */}
      <View style={[styles.row, { marginLeft: HEADER_W }]}>
        {col.labels.map((label, i) => (
          <TouchableOpacity
            key={i}
            style={{ width: cellW, alignItems: 'center' }}
            onPress={() => toggleCol(col.full[i])}
          >
            <Text style={[styles.colLabel, colSel(col.full[i]) && styles.colLabelActive]}>
              {label}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Data rows */}
      {TIME_OF_DAY.map((tod, ri) => (
        <View key={tod} style={styles.row}>
          <TouchableOpacity style={{ width: HEADER_W }} onPress={() => toggleRow(tod)}>
            <Text style={[styles.rowLabel, rowSel(tod) && styles.rowLabelActive]} numberOfLines={1}>
              {TOD_LABELS[ri]}
            </Text>
          </TouchableOpacity>
          {col.full.map((val, ci) => (
            <TouchableOpacity
              key={ci}
              activeOpacity={0.7}
              style={[
                styles.cell,
                {
                  width: cellW,
                  height: cellH,
                  backgroundColor: cellBg(col.counts[ci], rowSel(tod), colSel(val)),
                  borderColor: rowSel(tod) && colSel(val) ? 'rgba(22,162,153,0.3)' : 'rgba(0,0,0,0.06)',
                },
              ]}
              onPress={() => {
                toggleRow(tod);
                toggleCol(val);
              }}
            />
          ))}
        </View>
      ))}

      {/* Legend */}
      <View style={styles.legendRow}>
        <Text style={styles.legendText}>Tap row/col labels to filter · Tap cell to filter both</Text>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  root: {
    backgroundColor: COLORS.surface,
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderRadius: 12,
    marginHorizontal: 10,
    marginBottom: 6,
  },
  modeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 6,
  },
  heading: {
    fontSize: 11,
    fontWeight: '700',
    color: COLORS.textSecondary,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    flex: 1,
  },
  modeTabs: { flexDirection: 'row', gap: 4 },
  modeTab: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: COLORS.divider,
  },
  modeTabActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  modeTabText: { fontSize: 11, color: COLORS.textSecondary },
  modeTabTextActive: { color: '#fff', fontWeight: '600' },
  clearBtn: { fontSize: 11, color: COLORS.primary, marginLeft: 8 },
  row: { flexDirection: 'row', alignItems: 'center', marginBottom: 2 },
  colLabel: {
    fontSize: 9,
    color: COLORS.textSecondary,
    textAlign: 'center',
    paddingVertical: 2,
  },
  colLabelActive: { color: COLORS.primary, fontWeight: '700' },
  rowLabel: {
    fontSize: 9,
    color: COLORS.textSecondary,
    paddingRight: 4,
    textAlign: 'right',
  },
  rowLabelActive: { color: COLORS.primary, fontWeight: '700' },
  cell: {
    borderWidth: 1,
    borderRadius: 2,
    marginHorizontal: 1,
  },
  legendRow: { marginTop: 4 },
  legendText: { fontSize: 9, color: COLORS.textSecondary, textAlign: 'center' },
});

export default TimeHeatmap;

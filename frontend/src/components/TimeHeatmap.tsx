import { Box, Stack, Tooltip, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import dayjs from 'dayjs';
import dayOfYear from 'dayjs/plugin/dayOfYear';
import timezone from 'dayjs/plugin/timezone';
import utc from 'dayjs/plugin/utc';
import weekOfYear from 'dayjs/plugin/weekOfYear';
import weekYear from 'dayjs/plugin/weekYear';
import React, { useCallback, useMemo } from 'react';
import {
    DayOfWeek,
    Month,
    TimeOfDay,
    dayOfWeekOptions,
    monthOptions,
    timeOfDayOptions,
} from 'types/filters';
import { ImageObject } from 'utils/types';

dayjs.extend(weekOfYear);
dayjs.extend(weekYear);
dayjs.extend(dayOfYear);
dayjs.extend(utc);
dayjs.extend(timezone);

type ViewMode = 'weekday' | 'month' | 'calendar';

// Display order: chronological from morning to night
const TOD_DISPLAY: { key: TimeOfDay; label: string; sub: string }[] = [
    { key: 'morning',   label: 'Morning',   sub: '05–11' },
    { key: 'midday',    label: 'Midday',    sub: '11–13' },
    { key: 'afternoon', label: 'Afternoon', sub: '13–17' },
    { key: 'evening',   label: 'Evening',   sub: '17–21' },
    { key: 'night',     label: 'Night',     sub: '21–05' },
];

const DAY_ABBR = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const hourToTodKey = (h: number): TimeOfDay => {
    if (h >= 5 && h < 11) return 'morning';
    if (h >= 11 && h < 13) return 'midday';
    if (h >= 13 && h < 17) return 'afternoon';
    if (h >= 17 && h < 21) return 'evening';
    return 'night';
};

function toggle<T>(arr: T[], val: T): T[] {
    return arr.includes(val) ? arr.filter((x) => x !== val) : [...arr, val];
}

// ─── GridView ────────────────────────────────────────────────────────────────

const ROW_LABEL_W = 88;
const CELL_H = 48;

const GridView = ({
    rowItems,
    colLabels,
    selectedRows,
    selectedCols,
    density,
    onRowClick,
    onColClick,
}: {
    rowItems: { key: string; label: string; sub: string }[];
    colLabels: string[];
    selectedRows: number[];
    selectedCols: number[];
    density: number[][];
    onRowClick: (i: number) => void;
    onColClick: (i: number) => void;
}) => (
    <Box sx={{ display: 'flex', flexDirection: 'column', width: '100%', userSelect: 'none' }}>
        {/* Column headers */}
        <Box sx={{ display: 'flex', ml: `${ROW_LABEL_W}px` }}>
            {colLabels.map((label, ci) => {
                const active = selectedCols.includes(ci);
                return (
                    <Box
                        key={ci}
                        onClick={() => onColClick(ci)}
                        sx={{
                            flex: 1,
                            textAlign: 'center',
                            py: 0.75,
                            cursor: 'pointer',
                            fontSize: '0.68rem',
                            fontWeight: active ? 700 : 400,
                            color: active ? 'primary.main' : 'text.disabled',
                            borderRadius: '4px 4px 0 0',
                            bgcolor: active ? 'rgba(22,162,152,0.12)' : 'transparent',
                            transition: 'all 0.15s',
                            '&:hover': { color: 'primary.light', bgcolor: 'rgba(22,162,152,0.07)' },
                        }}
                    >
                        {label}
                    </Box>
                );
            })}
        </Box>

        {/* Rows */}
        {rowItems.map(({ label, sub }, ri) => {
            const rowActive = selectedRows.includes(ri);
            return (
                <Box key={ri} sx={{ display: 'flex', alignItems: 'stretch', mb: '2px' }}>
                    {/* Row label */}
                    <Box
                        onClick={() => onRowClick(ri)}
                        sx={{
                            width: ROW_LABEL_W,
                            minWidth: ROW_LABEL_W,
                            display: 'flex',
                            flexDirection: 'column',
                            justifyContent: 'center',
                            alignItems: 'flex-end',
                            pr: 1.5,
                            cursor: 'pointer',
                            color: rowActive ? 'primary.main' : 'text.disabled',
                            bgcolor: rowActive ? 'rgba(22,162,152,0.08)' : 'transparent',
                            borderRadius: '4px 0 0 4px',
                            transition: 'all 0.15s',
                            '&:hover': { color: 'primary.light', bgcolor: 'rgba(22,162,152,0.05)' },
                        }}
                    >
                        <Typography sx={{ fontSize: '0.7rem', fontWeight: rowActive ? 700 : 400, lineHeight: 1.2 }}>
                            {label}
                        </Typography>
                        <Typography sx={{ fontSize: '0.6rem', opacity: 0.6, lineHeight: 1.2 }}>
                            {sub}
                        </Typography>
                    </Box>

                    {/* Cells */}
                    {colLabels.map((_, ci) => {
                        const colActive = selectedCols.includes(ci);
                        const d = density[ri]?.[ci] ?? 0;
                        const both = rowActive && colActive;
                        let bg: string;
                        if (both) {
                            bg = `rgba(22,162,152,${0.28 + d * 0.52})`;
                        } else if (rowActive || colActive) {
                            bg = `rgba(22,162,152,${0.09 + d * 0.18})`;
                        } else if (d > 0) {
                            bg = `rgba(147,51,234,${0.12 + d * 0.48})`;
                        } else {
                            bg = 'rgba(255,255,255,0.04)';
                        }
                        return (
                            <Box
                                key={ci}
                                onClick={() => {
                                    // cell click: add row and col to filter (never removes)
                                    if (!selectedRows.includes(ri)) onRowClick(ri);
                                    if (!selectedCols.includes(ci)) onColClick(ci);
                                }}
                                sx={{
                                    flex: 1,
                                    height: CELL_H,
                                    bgcolor: bg,
                                    border: '1px solid rgba(255,255,255,0.05)',
                                    cursor: 'pointer',
                                    transition: 'all 0.1s',
                                    '&:hover': {
                                        filter: 'brightness(1.35)',
                                        border: '1px solid rgba(255,255,255,0.18)',
                                    },
                                }}
                            />
                        );
                    })}
                </Box>
            );
        })}
    </Box>
);

// ─── CalendarView ─────────────────────────────────────────────────────────────

const CSIZ = 11;
const CGAP = 2;

const CalendarView = ({
    calendarGrid,
    density,
    selectedDates,
    onDateClick,
}: {
    calendarGrid: (string | null)[][];
    density: (number | null)[][];
    selectedDates: Set<string>;
    onDateClick: (d: string) => void;
}) => {
    const monthLabels = useMemo(() => {
        const labels: { weekIdx: number; label: string }[] = [];
        let last = -1;
        calendarGrid.forEach((week, wi) => {
            const d = week.find(Boolean);
            if (d) {
                const m = dayjs(d).month();
                if (m !== last) {
                    labels.push({ weekIdx: wi, label: MONTH_ABBR[m] });
                    last = m;
                }
            }
        });
        return labels;
    }, [calendarGrid]);

    return (
        <Box sx={{ width: '100%', overflowX: 'auto', pb: 1 }}>
            {/* Month labels */}
            <Box sx={{ position: 'relative', height: 14, ml: `${CSIZ + CGAP + 6}px` }}>
                {monthLabels.map(({ weekIdx, label }) => (
                    <Typography
                        key={weekIdx}
                        sx={{
                            position: 'absolute',
                            left: weekIdx * (CSIZ + CGAP),
                            fontSize: '0.58rem',
                            color: 'text.secondary',
                            lineHeight: 1,
                            pointerEvents: 'none',
                        }}
                    >
                        {label}
                    </Typography>
                ))}
            </Box>

            <Box sx={{ display: 'flex', gap: `${CGAP}px`, alignItems: 'flex-start' }}>
                {/* Day-of-week labels (M W F S) */}
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: `${CGAP}px` }}>
                    {['M', '', 'W', '', 'F', '', 'S'].map((d, i) => (
                        <Typography
                            key={i}
                            sx={{
                                width: CSIZ,
                                height: CSIZ,
                                fontSize: '0.5rem',
                                color: 'text.disabled',
                                lineHeight: `${CSIZ}px`,
                                textAlign: 'center',
                            }}
                        >
                            {d}
                        </Typography>
                    ))}
                </Box>

                {/* Week columns */}
                {calendarGrid.map((week, wi) => (
                    <Box key={wi} sx={{ display: 'flex', flexDirection: 'column', gap: `${CGAP}px` }}>
                        {week.map((dateStr, di) => {
                            if (!dateStr) {
                                return <Box key={di} sx={{ width: CSIZ, height: CSIZ }} />;
                            }
                            const d = density[wi]?.[di] ?? 0;
                            const sel = selectedDates.has(dateStr);
                            const bg = sel
                                ? 'rgba(22,162,152,0.9)'
                                : d > 0
                                ? `rgba(147,51,234,${0.15 + d * 0.65})`
                                : 'rgba(255,255,255,0.07)';
                            return (
                                <Tooltip
                                    key={di}
                                    title={dayjs(dateStr).format('ddd D MMM YYYY')}
                                    placement="top"
                                    arrow
                                >
                                    <Box
                                        onClick={() => onDateClick(dateStr)}
                                        sx={{
                                            width: CSIZ,
                                            height: CSIZ,
                                            bgcolor: bg,
                                            borderRadius: '2px',
                                            border: sel
                                                ? '1px solid rgba(22,162,152,1)'
                                                : '1px solid transparent',
                                            cursor: 'pointer',
                                            transition: 'all 0.1s',
                                            '&:hover': { filter: 'brightness(1.6)' },
                                        }}
                                    />
                                </Tooltip>
                            );
                        })}
                    </Box>
                ))}
            </Box>
        </Box>
    );
};

// ─── Main component ───────────────────────────────────────────────────────────

export interface TimeHeatmapProps {
    timeOfDays: TimeOfDay[];
    dayOfWeeks: DayOfWeek[];
    months: Month[];
    currentYear: number;
    customRanges: { start: string; end: string }[];
    resultImages: ImageObject[];
    onTimeOfDaysChange: (v: TimeOfDay[]) => void;
    onDayOfWeeksChange: (v: DayOfWeek[]) => void;
    onMonthsChange: (v: Month[]) => void;
    onCustomRangesChange: (v: { start: string; end: string }[]) => void;
}

const TimeHeatmap = ({
    timeOfDays,
    dayOfWeeks,
    months,
    currentYear,
    customRanges,
    resultImages,
    onTimeOfDaysChange,
    onDayOfWeeksChange,
    onMonthsChange,
    onCustomRangesChange,
}: TimeHeatmapProps) => {
    const [view, setView] = React.useState<ViewMode>('weekday');

    // ── density grids ──────────────────────────────────────────────────────

    const weekdayDensity = useMemo(() => {
        const grid = Array.from({ length: 5 }, () => new Array(7).fill(0));
        for (const img of resultImages) {
            const ts = dayjs.utc(img.timestamp).tz(img.timezone || 'UTC');
            const ri = TOD_DISPLAY.findIndex((t) => t.key === hourToTodKey(ts.hour()));
            const ci = (ts.day() + 6) % 7;
            if (ri >= 0) grid[ri][ci]++;
        }
        const max = Math.max(...grid.flatMap((r) => r), 1);
        return grid.map((r) => r.map((v) => v / max));
    }, [resultImages]);

    const monthDensity = useMemo(() => {
        const grid = Array.from({ length: 5 }, () => new Array(12).fill(0));
        for (const img of resultImages) {
            const ts = dayjs.utc(img.timestamp).tz(img.timezone || 'UTC');
            if (ts.year() !== currentYear) continue;
            const ri = TOD_DISPLAY.findIndex((t) => t.key === hourToTodKey(ts.hour()));
            if (ri >= 0) grid[ri][ts.month()]++;
        }
        const max = Math.max(...grid.flatMap((r) => r), 1);
        return grid.map((r) => r.map((v) => v / max));
    }, [resultImages, currentYear]);

    const { calendarGrid, calendarDensity } = useMemo(() => {
        const start = dayjs(`${currentYear}-01-01`);
        const daysInYear = dayjs(`${currentYear}-12-31`).diff(start, 'day') + 1;
        const firstDow = (start.day() + 6) % 7;
        const numWeeks = Math.ceil((daysInYear + firstDow) / 7);

        const grid: (string | null)[][] = Array.from({ length: numWeeks }, () =>
            new Array(7).fill(null)
        );
        for (let d = 0; d < daysInYear; d++) {
            const date = start.add(d, 'day');
            const dow = (date.day() + 6) % 7;
            const wi = Math.floor((d + firstDow) / 7);
            grid[wi][dow] = date.format('YYYY-MM-DD');
        }

        const counts: Record<string, number> = {};
        for (const img of resultImages) {
            const ts = dayjs.utc(img.timestamp).tz(img.timezone || 'UTC');
            if (ts.year() !== currentYear) continue;
            const k = ts.format('YYYY-MM-DD');
            counts[k] = (counts[k] || 0) + 1;
        }
        const maxC = Math.max(...Object.values(counts), 1);
        const density = grid.map((week) =>
            week.map((d) => (d === null ? null : (counts[d] || 0) / maxC))
        );

        return { calendarGrid: grid, calendarDensity: density };
    }, [currentYear, resultImages]);

    // ── selected indices ───────────────────────────────────────────────────

    const selectedTodIndices = useMemo(
        () => timeOfDays.map((t) => TOD_DISPLAY.findIndex((d) => d.key === t)).filter((i) => i >= 0),
        [timeOfDays]
    );
    const selectedDowIndices = useMemo(
        () => dayOfWeeks.map((d) => dayOfWeekOptions.indexOf(d)).filter((i) => i >= 0),
        [dayOfWeeks]
    );
    const selectedMonthIndices = useMemo(
        () => months.map((m) => monthOptions.indexOf(m)).filter((i) => i >= 0),
        [months]
    );
    const selectedDates = useMemo(
        () => new Set(customRanges.filter((r) => r.start === r.end).map((r) => r.start)),
        [customRanges]
    );

    // ── toggle callbacks ───────────────────────────────────────────────────

    const toggleTod = useCallback(
        (i: number) => onTimeOfDaysChange(toggle(timeOfDays, TOD_DISPLAY[i].key)),
        [timeOfDays, onTimeOfDaysChange]
    );
    const toggleDow = useCallback(
        (i: number) => onDayOfWeeksChange(toggle(dayOfWeeks, dayOfWeekOptions[i])),
        [dayOfWeeks, onDayOfWeeksChange]
    );
    const toggleMonth = useCallback(
        (i: number) => onMonthsChange(toggle(months, monthOptions[i])),
        [months, onMonthsChange]
    );
    const toggleDate = useCallback(
        (dateStr: string) => {
            const exists = customRanges.some((r) => r.start === dateStr && r.end === dateStr);
            onCustomRangesChange(
                exists
                    ? customRanges.filter((r) => !(r.start === dateStr && r.end === dateStr))
                    : [...customRanges, { start: dateStr, end: dateStr }]
            );
        },
        [customRanges, onCustomRangesChange]
    );

    // ── render ─────────────────────────────────────────────────────────────

    return (
        <Box sx={{ width: '100%' }}>
            <Stack direction="row" alignItems="center" mb={1.5}>
                <ToggleButtonGroup
                    size="small"
                    value={view}
                    exclusive
                    onChange={(_, v) => v && setView(v)}
                >
                    <ToggleButton value="weekday" sx={{ px: 1.5, py: 0.5, fontSize: '0.72rem' }}>
                        Week
                    </ToggleButton>
                    <ToggleButton value="month" sx={{ px: 1.5, py: 0.5, fontSize: '0.72rem' }}>
                        Month
                    </ToggleButton>
                    <ToggleButton value="calendar" sx={{ px: 1.5, py: 0.5, fontSize: '0.72rem' }}>
                        Calendar
                    </ToggleButton>
                </ToggleButtonGroup>
                <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ ml: 'auto !important', fontSize: '0.65rem' }}
                >
                    {view === 'calendar'
                        ? 'Click days to pin specific dates'
                        : 'Click row / column labels to filter · click cells to add both'}
                </Typography>
            </Stack>

            {view === 'weekday' && (
                <GridView
                    rowItems={TOD_DISPLAY}
                    colLabels={DAY_ABBR}
                    selectedRows={selectedTodIndices}
                    selectedCols={selectedDowIndices}
                    density={weekdayDensity}
                    onRowClick={toggleTod}
                    onColClick={toggleDow}
                />
            )}

            {view === 'month' && (
                <GridView
                    rowItems={TOD_DISPLAY}
                    colLabels={MONTH_ABBR}
                    selectedRows={selectedTodIndices}
                    selectedCols={selectedMonthIndices}
                    density={monthDensity}
                    onRowClick={toggleTod}
                    onColClick={toggleMonth}
                />
            )}

            {view === 'calendar' && (
                <CalendarView
                    calendarGrid={calendarGrid}
                    density={calendarDensity}
                    selectedDates={selectedDates}
                    onDateClick={toggleDate}
                />
            )}
        </Box>
    );
};

// Keep re-exporting unused option arrays so other files don't need to change
export { timeOfDayOptions };
export default TimeHeatmap;

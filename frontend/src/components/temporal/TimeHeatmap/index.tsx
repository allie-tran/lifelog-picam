import { Box, Stack, Typography, ToggleButton, ToggleButtonGroup, Button, Menu, MenuItem } from '@mui/material';
import { KeyboardArrowDownRounded } from '@mui/icons-material';
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
import { HeatmapData } from 'apis/browsing';
import GridView from './GridView';
import CalendarView from './CalendarView';
import {
    TOD_DISPLAY,
    DAY_ABBR,
    MONTH_ABBR,
    HOUR_ROWS,
    hourToTodKey,
    hourToTodIndex,
    toggle,
    ViewMode,
} from './constants';

dayjs.extend(weekOfYear);
dayjs.extend(weekYear);
dayjs.extend(dayOfYear);
dayjs.extend(utc);
dayjs.extend(timezone);

// ── grid builder ────────────────────────────────────────────────────────────
// Aggregate a server-side density tuple list into a {density, counts, totals}
// grid. density is per-grid normalized [0,1]; counts/totals are absolute.
type Tuple4 = [number, number, number, number];
function buildGrid(
    rows: number,
    cols: number,
    data: Tuple4[],
    rowOf: (t: Tuple4) => number,
    colOf: (t: Tuple4) => number,
    yearFilter: number | null
) {
    const counts = Array.from({ length: rows }, () => new Array(cols).fill(0));
    for (const t of data) {
        if (yearFilter !== null && t[0] !== yearFilter) continue;
        const r = rowOf(t);
        const c = colOf(t);
        if (r < 0 || r >= rows || c < 0 || c >= cols) continue;
        counts[r][c] += t[3];
    }
    const max = Math.max(...counts.flatMap((r) => r), 1);
    const density = counts.map((r) => r.map((v) => v / max));
    const rowTotals = counts.map((r) => r.reduce((a, b) => a + b, 0));
    const colTotals = Array.from({ length: cols }, (_, c) =>
        counts.reduce((s, r) => s + r[c], 0)
    );
    return { density, counts, rowTotals, colTotals };
}

const addUnion = <T,>(current: T[], add: T[]): T[] => Array.from(new Set([...current, ...add]));

export interface TimeHeatmapProps {
    timeOfDays: TimeOfDay[];
    dayOfWeeks: DayOfWeek[];
    months: Month[];
    years: number[];
    currentYear: number | null;
    customRanges: { start: string; end: string }[];
    weekCells: { timeOfDay: TimeOfDay; dayOfWeek: DayOfWeek }[];
    monthCells: { dayOfWeek: DayOfWeek; month: Month }[];
    heatmap: HeatmapData;
    onTimeOfDaysChange: (v: TimeOfDay[]) => void;
    onDayOfWeeksChange: (v: DayOfWeek[]) => void;
    onMonthsChange: (v: Month[]) => void;
    onYearsChange: (v: number[]) => void;
    onCustomRangesChange: (v: { start: string; end: string }[]) => void;
    // Atomic combined handlers for cell clicks (row+col in one URL update)
    onWeekdayCellClick: (tod: TimeOfDay, dow: DayOfWeek) => void;
    onMonthCellClick: (dow: DayOfWeek, month: Month) => void;
}

const PRIMARY_VIEWS: ViewMode[] = ['weekday', 'month', 'calendar'];
const MORE_VIEWS: { value: ViewMode; label: string }[] = [
    { value: 'hourDow', label: 'Hour × Day' },
    { value: 'hourMonth', label: 'Hour × Month' },
    { value: 'trend', label: 'Year trend' },
];
const VIEW_LABELS: Record<ViewMode, string> = {
    weekday: 'Week',
    month: 'Month',
    calendar: 'Calendar',
    hourDow: 'Hour × Day',
    hourMonth: 'Hour × Month',
    trend: 'Year trend',
};

const TimeHeatmap = ({
    timeOfDays,
    dayOfWeeks,
    months,
    years,
    currentYear,
    customRanges,
    weekCells,
    monthCells,
    heatmap,
    onTimeOfDaysChange,
    onDayOfWeeksChange,
    onMonthsChange,
    onYearsChange,
    onCustomRangesChange,
    onWeekdayCellClick,
    onMonthCellClick,
}: TimeHeatmapProps) => {
    const [view, setView] = React.useState<ViewMode>('month');
    const [moreAnchor, setMoreAnchor] = React.useState<null | HTMLElement>(null);

    // ── density grids ──────────────────────────────────────────────────────
    // Densities are pre-aggregated server-side (see backend retrieve_image_with
    // _filters); building the grids here is a handful of tiny loops.

    const weekday = useMemo(
        () => buildGrid(5, 7, heatmap.weekdayTod as Tuple4[], (t) => t[2], (t) => t[1], currentYear),
        [heatmap, currentYear]
    );
    const month = useMemo(
        () => buildGrid(7, 12, heatmap.weekdayMonth as Tuple4[], (t) => t[1], (t) => t[2], currentYear),
        [heatmap, currentYear]
    );
    const hourDow = useMemo(
        () => buildGrid(24, 7, heatmap.hourDow as Tuple4[], (t) => t[1], (t) => t[2], currentYear),
        [heatmap, currentYear]
    );
    const hourMonth = useMemo(
        () => buildGrid(24, 12, heatmap.hourMonth as Tuple4[], (t) => t[1], (t) => t[2], currentYear),
        [heatmap, currentYear]
    );

    // Year-trend rows are the result years (ascending). It ignores the year-chip
    // filter on purpose — the whole point is the cross-year comparison.
    const trendYears = useMemo(() => [...heatmap.years].sort((a, b) => a - b), [heatmap.years]);
    const trend = useMemo(
        () =>
            buildGrid(
                trendYears.length,
                12,
                heatmap.weekdayMonth as Tuple4[],
                (t) => trendYears.indexOf(t[0]),
                (t) => t[2],
                null
            ),
        [heatmap, trendYears]
    );

    const calendarYear = currentYear ??
        (heatmap.years.length > 0
            ? Math.max(...heatmap.years)
            : new Date().getFullYear());

    const { calendarGrid, calendarDensity } = useMemo(() => {
        const start = dayjs(`${calendarYear}-01-01`);
        const daysInYear = dayjs(`${calendarYear}-12-31`).diff(start, 'day') + 1;
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
        for (const [dateStr, count] of heatmap.calendar) {
            counts[dateStr] = count;
        }
        const gridDates = grid.flat().filter(Boolean) as string[];
        const maxC = Math.max(...gridDates.map((d) => counts[d] ?? 0), 1);
        const density = grid.map((week) =>
            week.map((d) => (d === null ? null : (counts[d] ?? 0) / maxC))
        );

        return { calendarGrid: grid, calendarDensity: density };
    }, [calendarYear, heatmap]);

    // ── selected indices (row/col from checkboxes) ─────────────────────────

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
    // Hour rows count as selected when their time-of-day bucket is selected.
    const selectedHourIndices = useMemo(
        () => HOUR_ROWS.map((_, h) => h).filter((h) => timeOfDays.includes(hourToTodKey(h))),
        [timeOfDays]
    );
    const selectedTrendRowIndices = useMemo(
        () => trendYears.map((y, i) => [y, i] as const).filter(([y]) => years.includes(y)).map(([, i]) => i),
        [trendYears, years]
    );

    const selectedDates = useMemo(() => {
        const set = new Set<string>();
        for (const r of customRanges) {
            let d = dayjs(r.start);
            const end = dayjs(r.end);
            while (!d.isAfter(end)) {
                set.add(d.format('YYYY-MM-DD'));
                d = d.add(1, 'day');
            }
        }
        return set;
    }, [customRanges]);

    // For calendar cross-highlighting (only when a specific year is selected)
    const calendarHighlightDows = useMemo(
        () =>
            currentYear !== null
                ? new Set(weekCells.map((c) => dayOfWeekOptions.indexOf(c.dayOfWeek)))
                : new Set<number>(),
        [weekCells, currentYear]
    );
    const calendarHighlightDowMonthPairs = useMemo(
        () =>
            currentYear !== null
                ? new Set(monthCells.map((c) =>
                      `${dayOfWeekOptions.indexOf(c.dayOfWeek)}:${monthOptions.indexOf(c.month)}`
                  ))
                : new Set<string>(),
        [monthCells, currentYear]
    );

    // ── toggle callbacks (labels) ────────────────────────────────────────────

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
    // Hour row label → toggle its time-of-day bucket.
    const toggleHourTod = useCallback(
        (h: number) => onTimeOfDaysChange(toggle(timeOfDays, TOD_DISPLAY[hourToTodIndex(h)].key)),
        [timeOfDays, onTimeOfDaysChange]
    );
    const toggleYearRow = useCallback(
        (i: number) => onYearsChange(toggle(years, trendYears[i])),
        [years, trendYears, onYearsChange]
    );

    // ── cell click bridges (toggle row + col) ─────────────────────────────────

    const handleWeekdayCellClick = useCallback(
        (ri: number, ci: number) => onWeekdayCellClick(TOD_DISPLAY[ri].key, dayOfWeekOptions[ci]),
        [onWeekdayCellClick]
    );
    const handleMonthCellClick = useCallback(
        (ri: number, ci: number) => onMonthCellClick(dayOfWeekOptions[ri], monthOptions[ci]),
        [onMonthCellClick]
    );
    const handleHourDowCellClick = useCallback(
        (ri: number, ci: number) => {
            onTimeOfDaysChange(toggle(timeOfDays, TOD_DISPLAY[hourToTodIndex(ri)].key));
            onDayOfWeeksChange(toggle(dayOfWeeks, dayOfWeekOptions[ci]));
        },
        [timeOfDays, dayOfWeeks, onTimeOfDaysChange, onDayOfWeeksChange]
    );
    const handleHourMonthCellClick = useCallback(
        (ri: number, ci: number) => {
            onTimeOfDaysChange(toggle(timeOfDays, TOD_DISPLAY[hourToTodIndex(ri)].key));
            onMonthsChange(toggle(months, monthOptions[ci]));
        },
        [timeOfDays, months, onTimeOfDaysChange, onMonthsChange]
    );
    const handleTrendCellClick = useCallback(
        (ri: number, ci: number) => {
            onYearsChange(toggle(years, trendYears[ri]));
            onMonthsChange(toggle(months, monthOptions[ci]));
        },
        [years, months, trendYears, onYearsChange, onMonthsChange]
    );

    // ── drag range select (rectangle of rows × cols) ──────────────────────────

    const hourRowsToTods = (rows: number[]) =>
        Array.from(new Set(rows.map((h) => TOD_DISPLAY[hourToTodIndex(h)].key)));

    const onWeekdayRange = useCallback(
        (rows: number[], cols: number[]) => {
            onTimeOfDaysChange(addUnion(timeOfDays, rows.map((i) => TOD_DISPLAY[i].key)));
            onDayOfWeeksChange(addUnion(dayOfWeeks, cols.map((i) => dayOfWeekOptions[i])));
        },
        [timeOfDays, dayOfWeeks, onTimeOfDaysChange, onDayOfWeeksChange]
    );
    const onMonthRange = useCallback(
        (rows: number[], cols: number[]) => {
            onDayOfWeeksChange(addUnion(dayOfWeeks, rows.map((i) => dayOfWeekOptions[i])));
            onMonthsChange(addUnion(months, cols.map((i) => monthOptions[i])));
        },
        [dayOfWeeks, months, onDayOfWeeksChange, onMonthsChange]
    );
    const onHourDowRange = useCallback(
        (rows: number[], cols: number[]) => {
            onTimeOfDaysChange(addUnion(timeOfDays, hourRowsToTods(rows)));
            onDayOfWeeksChange(addUnion(dayOfWeeks, cols.map((i) => dayOfWeekOptions[i])));
        },
        [timeOfDays, dayOfWeeks, onTimeOfDaysChange, onDayOfWeeksChange]
    );
    const onHourMonthRange = useCallback(
        (rows: number[], cols: number[]) => {
            onTimeOfDaysChange(addUnion(timeOfDays, hourRowsToTods(rows)));
            onMonthsChange(addUnion(months, cols.map((i) => monthOptions[i])));
        },
        [timeOfDays, months, onTimeOfDaysChange, onMonthsChange]
    );
    const onTrendRange = useCallback(
        (rows: number[], cols: number[]) => {
            onYearsChange(addUnion(years, rows.map((i) => trendYears[i])));
            onMonthsChange(addUnion(months, cols.map((i) => monthOptions[i])));
        },
        [years, months, trendYears, onYearsChange, onMonthsChange]
    );

    // ── calendar handlers ──────────────────────────────────────────────────

    const toggleDate = useCallback(
        (dateStr: string) => {
            const inRange = customRanges.some((r) => dateStr >= r.start && dateStr <= r.end);
            if (inRange) {
                onCustomRangesChange(
                    customRanges.filter((r) => !(dateStr >= r.start && dateStr <= r.end))
                );
            } else {
                onCustomRangesChange([...customRanges, { start: dateStr, end: dateStr }]);
            }
        },
        [customRanges, onCustomRangesChange]
    );

    const handleCalendarDragSelect = useCallback(
        (dates: string[], mode: 'add' | 'remove') => {
            const sorted = [...dates].sort();
            const lo = sorted[0];
            const hi = sorted[sorted.length - 1];
            if (mode === 'add') {
                onCustomRangesChange([...customRanges, { start: lo, end: hi }]);
            } else {
                onCustomRangesChange(
                    customRanges.filter((r) => !(r.start >= lo && r.end <= hi) && !(r.start === r.end && r.start >= lo && r.start <= hi))
                );
            }
        },
        [customRanges, onCustomRangesChange]
    );

    // ── render ─────────────────────────────────────────────────────────────

    const moreActive = !PRIMARY_VIEWS.includes(view);
    const hint =
        view === 'calendar'
            ? 'Click a date · drag to select a range · drag over selected to remove'
            : view === 'trend'
                ? 'Rows are years (all results) · click or drag cells to filter'
                : 'Click or drag cells to toggle · hover for counts';

    return (
        <Box sx={{ width: '100%' }}>
            <Stack direction="row" alignItems="center" mb={1.5} spacing={1}>
                <ToggleButtonGroup
                    size="small"
                    value={PRIMARY_VIEWS.includes(view) ? view : null}
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

                <Button
                    size="small"
                    variant={moreActive ? 'contained' : 'outlined'}
                    color={moreActive ? 'secondary' : 'inherit'}
                    endIcon={<KeyboardArrowDownRounded />}
                    onClick={(e) => setMoreAnchor(e.currentTarget)}
                    sx={{ px: 1.5, py: 0.5, fontSize: '0.72rem', textTransform: 'none' }}
                >
                    {moreActive ? VIEW_LABELS[view] : 'More'}
                </Button>
                <Menu anchorEl={moreAnchor} open={Boolean(moreAnchor)} onClose={() => setMoreAnchor(null)}>
                    {MORE_VIEWS.map((v) => (
                        <MenuItem
                            key={v.value}
                            selected={view === v.value}
                            onClick={() => {
                                setView(v.value);
                                setMoreAnchor(null);
                            }}
                            sx={{ fontSize: '0.78rem' }}
                        >
                            {v.label}
                        </MenuItem>
                    ))}
                </Menu>

                <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ ml: 'auto !important', fontSize: '0.65rem' }}
                >
                    {hint}
                </Typography>
            </Stack>

            {view === 'weekday' && (
                <GridView
                    rowItems={TOD_DISPLAY}
                    colLabels={DAY_ABBR}
                    selectedRows={selectedTodIndices}
                    selectedCols={selectedDowIndices}
                    density={weekday.density}
                    counts={weekday.counts}
                    rowTotals={weekday.rowTotals}
                    colTotals={weekday.colTotals}
                    onRowClick={toggleTod}
                    onColClick={toggleDow}
                    onCellClick={handleWeekdayCellClick}
                    onRangeSelect={onWeekdayRange}
                    cellH={18}
                />
            )}

            {view === 'month' && (
                <GridView
                    rowItems={DAY_ABBR.map((label) => ({ key: label, label, sub: '' }))}
                    colLabels={MONTH_ABBR}
                    selectedRows={selectedDowIndices}
                    selectedCols={selectedMonthIndices}
                    density={month.density}
                    counts={month.counts}
                    rowTotals={month.rowTotals}
                    colTotals={month.colTotals}
                    onRowClick={toggleDow}
                    onColClick={toggleMonth}
                    onCellClick={handleMonthCellClick}
                    onRangeSelect={onMonthRange}
                    cellH={16}
                />
            )}

            {view === 'hourDow' && (
                <GridView
                    rowItems={HOUR_ROWS}
                    colLabels={DAY_ABBR}
                    selectedRows={selectedHourIndices}
                    selectedCols={selectedDowIndices}
                    density={hourDow.density}
                    counts={hourDow.counts}
                    rowTotals={hourDow.rowTotals}
                    colTotals={hourDow.colTotals}
                    onRowClick={toggleHourTod}
                    onColClick={toggleDow}
                    onCellClick={handleHourDowCellClick}
                    onRangeSelect={onHourDowRange}
                    cellH={9}
                />
            )}

            {view === 'hourMonth' && (
                <GridView
                    rowItems={HOUR_ROWS}
                    colLabels={MONTH_ABBR}
                    selectedRows={selectedHourIndices}
                    selectedCols={selectedMonthIndices}
                    density={hourMonth.density}
                    counts={hourMonth.counts}
                    rowTotals={hourMonth.rowTotals}
                    colTotals={hourMonth.colTotals}
                    onRowClick={toggleHourTod}
                    onColClick={toggleMonth}
                    onCellClick={handleHourMonthCellClick}
                    onRangeSelect={onHourMonthRange}
                    cellH={9}
                />
            )}

            {view === 'trend' && (
                trendYears.length > 0 ? (
                    <GridView
                        rowItems={trendYears.map((y) => ({ key: String(y), label: String(y), sub: '' }))}
                        colLabels={MONTH_ABBR}
                        selectedRows={selectedTrendRowIndices}
                        selectedCols={selectedMonthIndices}
                        density={trend.density}
                        counts={trend.counts}
                        rowTotals={trend.rowTotals}
                        colTotals={trend.colTotals}
                        onRowClick={toggleYearRow}
                        onColClick={toggleMonth}
                        onCellClick={handleTrendCellClick}
                        onRangeSelect={onTrendRange}
                        cellH={20}
                    />
                ) : (
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', py: 2 }}>
                        No results to chart across years.
                    </Typography>
                )
            )}

            {view === 'calendar' && (() => {
                const hasResultsInYear = heatmap.years.includes(calendarYear);
                return (
                    <>
                        {heatmap.years.length > 0 && !hasResultsInYear && (
                            <Typography
                                variant="caption"
                                color="text.secondary"
                                sx={{ display: 'block', mb: 1, fontSize: '0.65rem' }}
                            >
                                No results in {calendarYear} — use the year chips above to navigate.
                            </Typography>
                        )}
                        <CalendarView
                            calendarGrid={calendarGrid}
                            density={calendarDensity}
                            selectedDates={selectedDates}
                            highlightedDows={calendarHighlightDows}
                            highlightedDowMonthPairs={calendarHighlightDowMonthPairs}
                            onDateClick={toggleDate}
                            onDragSelect={handleCalendarDragSelect}
                            showDowLabels={currentYear !== null}
                        />
                    </>
                );
            })()}
        </Box>
    );
};

// Keep re-exporting unused option arrays so other files don't need to change
export { timeOfDayOptions };
export default TimeHeatmap;

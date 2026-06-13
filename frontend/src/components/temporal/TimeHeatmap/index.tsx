import { Box, Stack, Typography, ToggleButton, ToggleButtonGroup } from '@mui/material';
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
import GridView from './GridView';
import CalendarView from './CalendarView';
import {
    TOD_DISPLAY,
    DAY_ABBR,
    MONTH_ABBR,
    hourToTodKey,
    toggle,
    ViewMode,
} from './constants';

dayjs.extend(weekOfYear);
dayjs.extend(weekYear);
dayjs.extend(dayOfYear);
dayjs.extend(utc);
dayjs.extend(timezone);

export interface TimeHeatmapProps {
    timeOfDays: TimeOfDay[];
    dayOfWeeks: DayOfWeek[];
    months: Month[];
    currentYear: number | null;
    customRanges: { start: string; end: string }[];
    weekCells: { timeOfDay: TimeOfDay; dayOfWeek: DayOfWeek }[];
    monthCells: { dayOfWeek: DayOfWeek; month: Month }[];
    resultImages: ImageObject[];
    onTimeOfDaysChange: (v: TimeOfDay[]) => void;
    onDayOfWeeksChange: (v: DayOfWeek[]) => void;
    onMonthsChange: (v: Month[]) => void;
    onCustomRangesChange: (v: { start: string; end: string }[]) => void;
    onWeekCellsChange: (v: { timeOfDay: TimeOfDay; dayOfWeek: DayOfWeek }[]) => void;
    onMonthCellsChange: (v: { dayOfWeek: DayOfWeek; month: Month }[]) => void;
    // Atomic combined handlers for cell clicks (row+col in one URL update)
    onWeekdayCellClick: (tod: TimeOfDay, dow: DayOfWeek) => void;
    onMonthCellClick: (dow: DayOfWeek, month: Month) => void;
}

const TimeHeatmap = ({
    timeOfDays,
    dayOfWeeks,
    months,
    currentYear,
    customRanges,
    weekCells,
    monthCells,
    resultImages,
    onTimeOfDaysChange,
    onDayOfWeeksChange,
    onMonthsChange,
    onCustomRangesChange,
    onWeekCellsChange,
    onMonthCellsChange,
    onWeekdayCellClick,
    onMonthCellClick,
}: TimeHeatmapProps) => {
    const [view, setView] = React.useState<ViewMode>('month');

    // ── density grids ──────────────────────────────────────────────────────

    const weekdayDensity = useMemo(() => {
        const grid = Array.from({ length: 5 }, () => new Array(7).fill(0));
        for (const img of resultImages) {
            const ts = dayjs.utc(img.timestamp).tz(img.timezone || 'UTC');
            if (currentYear !== null && ts.year() !== currentYear) continue;
            const ri = TOD_DISPLAY.findIndex((t) => t.key === hourToTodKey(ts.hour()));
            const ci = (ts.day() + 6) % 7;
            if (ri >= 0) grid[ri][ci]++;
        }
        const max = Math.max(...grid.flatMap((r) => r), 1);
        return grid.map((r) => r.map((v) => v / max));
    }, [resultImages, currentYear]);

    const monthDensity = useMemo(() => {
        const grid = Array.from({ length: 7 }, () => new Array(12).fill(0));
        for (const img of resultImages) {
            const ts = dayjs.utc(img.timestamp).tz(img.timezone || 'UTC');
            if (currentYear !== null && ts.year() !== currentYear) continue;
            const ri = (ts.day() + 6) % 7; // 0=Mon..6=Sun
            grid[ri][ts.month()]++;
        }
        const max = Math.max(...grid.flatMap((r) => r), 1);
        return grid.map((r) => r.map((v) => v / max));
    }, [resultImages, currentYear]);

    const calendarYear = currentYear ??
        (resultImages.length > 0
            ? Math.max(...resultImages.map((img) => dayjs.utc(img.timestamp).year()))
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
        for (const img of resultImages) {
            const k = dayjs.utc(img.timestamp).tz(img.timezone || 'UTC').format('YYYY-MM-DD');
            counts[k] = (counts[k] || 0) + 1;
        }
        // Normalize only against dates within the displayed year so other years
        // don't deflate the density scale.
        const gridDates = grid.flat().filter(Boolean) as string[];
        const maxC = Math.max(...gridDates.map((d) => counts[d] ?? 0), 1);
        const density = grid.map((week) =>
            week.map((d) => (d === null ? null : (counts[d] ?? 0) / maxC))
        );

        return { calendarGrid: grid, calendarDensity: density };
    }, [calendarYear, resultImages]);

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
    // monthCells = {dayOfWeek, month} pairs — highlight exact (dow, month) combinations
    const calendarHighlightDowMonthPairs = useMemo(
        () =>
            currentYear !== null
                ? new Set(monthCells.map((c) =>
                      `${dayOfWeekOptions.indexOf(c.dayOfWeek)}:${monthOptions.indexOf(c.month)}`
                  ))
                : new Set<string>(),
        [monthCells, currentYear]
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


    // Bridge: convert (ri,ci) indices → typed keys, then call the atomic prop
    const handleWeekdayCellClick = useCallback(
        (ri: number, ci: number) => onWeekdayCellClick(TOD_DISPLAY[ri].key, dayOfWeekOptions[ci]),
        [onWeekdayCellClick]
    );
    const handleMonthCellClick = useCallback(
        (ri: number, ci: number) => onMonthCellClick(dayOfWeekOptions[ri], monthOptions[ci]),
        [onMonthCellClick]
    );

    const toggleDate = useCallback(
        (dateStr: string) => {
            // A date is "selected" if it falls within any range
            const inRange = customRanges.some(
                (r) => dateStr >= r.start && dateStr <= r.end
            );
            if (inRange) {
                // Remove any range that contains this date (remove the whole range)
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
                // Remove any range that overlaps with the dragged span
                onCustomRangesChange(
                    customRanges.filter((r) => !(r.start >= lo && r.end <= hi) && !(r.start === r.end && r.start >= lo && r.start <= hi))
                );
            }
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
                        ? 'Click a date · drag to select a range · drag over selected to remove'
                        : 'Click labels or cells to toggle row + column'}
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
                    onCellClick={handleWeekdayCellClick}
                    cellH={18}
                />
            )}

            {view === 'month' && (
                <GridView
                    rowItems={DAY_ABBR.map((label) => ({ key: label, label, sub: '' }))}
                    colLabels={MONTH_ABBR}
                    selectedRows={selectedDowIndices}
                    selectedCols={selectedMonthIndices}
                    density={monthDensity}
                    onRowClick={toggleDow}
                    onColClick={toggleMonth}
                    onCellClick={handleMonthCellClick}
                    cellH={16}
                />
            )}

            {view === 'calendar' && (() => {
                const hasResultsInYear = resultImages.some(
                    (img) => dayjs.utc(img.timestamp).tz(img.timezone || 'UTC').year() === calendarYear
                );
                return (
                    <>
                        {resultImages.length > 0 && !hasResultsInYear && (
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

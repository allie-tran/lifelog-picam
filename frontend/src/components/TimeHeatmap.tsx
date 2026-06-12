import { Box, Stack, Tooltip, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import dayjs from 'dayjs';
import dayOfYear from 'dayjs/plugin/dayOfYear';
import timezone from 'dayjs/plugin/timezone';
import utc from 'dayjs/plugin/utc';
import weekOfYear from 'dayjs/plugin/weekOfYear';
import weekYear from 'dayjs/plugin/weekYear';
import React, { useCallback, useMemo, useState } from 'react';
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
const CELL_H = 24;

const GridView = ({
    rowItems,
    colLabels,
    selectedRows,
    selectedCols,
    density,
    onRowClick,
    onColClick,
    onCellClick,
    cellH = CELL_H,
}: {
    rowItems: { key: string; label: string; sub: string }[];
    colLabels: string[];
    selectedRows: number[];
    selectedCols: number[];
    density: number[][];
    onRowClick: (i: number) => void;
    onColClick: (i: number) => void;
    onCellClick: (ri: number, ci: number) => void;
    cellH?: number;
}) => {
    const [hovered, setHovered] = useState<{ ri: number; ci: number } | null>(null);

    return (
        <Box sx={{ display: 'flex', flexDirection: 'column', width: '100%', userSelect: 'none' }}>
            {/* Column headers */}
            <Box sx={{ display: 'flex', ml: `${ROW_LABEL_W}px` }}>
                {colLabels.map((label, ci) => {
                    const active = selectedCols.includes(ci);
                    const hovering = hovered?.ci === ci;
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
                                fontWeight: active || hovering ? 700 : 400,
                                color: active ? 'primary.main' : hovering ? 'primary.light' : 'text.disabled',
                                borderRadius: '4px 4px 0 0',
                                bgcolor: active ? 'rgba(22,162,152,0.12)' : hovering ? 'rgba(22,162,152,0.07)' : 'transparent',
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
                const rowHovering = hovered?.ri === ri;
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
                                color: rowActive ? 'primary.main' : rowHovering ? 'primary.light' : 'text.disabled',
                                bgcolor: rowActive ? 'rgba(22,162,152,0.08)' : rowHovering ? 'rgba(22,162,152,0.05)' : 'transparent',
                                borderRadius: '4px 0 0 4px',
                                transition: 'all 0.15s',
                                '&:hover': { color: 'primary.light', bgcolor: 'rgba(22,162,152,0.05)' },
                            }}
                        >
                            <Typography sx={{ fontSize: '0.7rem', fontWeight: rowActive || rowHovering ? 700 : 400, lineHeight: 1.2 }}>
                                {label}
                            </Typography>
                            <Typography sx={{ fontSize: '0.6rem', opacity: 0.6, lineHeight: 1.2 }}>
                                {sub}
                            </Typography>
                        </Box>

                        {/* Cells */}
                        {colLabels.map((_, ci) => {
                            const colActive = selectedCols.includes(ci);
                            const isHovered = hovered?.ri === ri && hovered?.ci === ci;
                            const rowOrColHovered = hovered?.ri === ri || hovered?.ci === ci;
                            const d = density[ri]?.[ci] ?? 0;
                            let bg: string;
                            if (rowActive && colActive) {
                                bg = `rgba(22,162,152,${0.22 + d * 0.38})`;
                            } else if (rowActive || colActive) {
                                bg = `rgba(22,162,152,${0.09 + d * 0.18})`;
                            } else if (rowOrColHovered) {
                                bg = `rgba(22,162,152,${0.06 + d * 0.12})`;
                            } else if (d > 0) {
                                bg = `rgba(147,51,234,${0.12 + d * 0.48})`;
                            } else {
                                bg = 'rgba(0,0,0,0.04)';
                            }
                            return (
                                <Box
                                    key={ci}
                                    onClick={(e) => { e.stopPropagation(); onCellClick(ri, ci); }}
                                    onMouseEnter={() => setHovered({ ri, ci })}
                                    onMouseLeave={() => setHovered(null)}
                                    sx={{
                                        flex: 1,
                                        height: cellH,
                                        bgcolor: bg,
                                        m: '1px',
                                        borderRadius: '4px',
                                        border: isHovered
                                            ? '1px solid rgba(22,162,152,0.5)'
                                            : '1px solid rgba(255,255,255,0.12)',
                                        cursor: 'pointer',
                                        transition: 'all 0.1s',
                                    }}
                                />
                            );
                        })}
                    </Box>
                );
            })}
        </Box>
    );
};

// ─── CalendarView ─────────────────────────────────────────────────────────────

const CSIZ = 17;
const CGAP = 2;

const CalendarView = ({
    calendarGrid,
    density,
    selectedDates,
    highlightedDows,
    highlightedDowMonthPairs,
    onDateClick,
    onDragSelect,
}: {
    calendarGrid: (string | null)[][];
    density: (number | null)[][];
    selectedDates: Set<string>;
    highlightedDows: Set<number>;
    highlightedDowMonthPairs: Set<string>;
    onDateClick: (d: string) => void;
    onDragSelect: (dates: string[], mode: 'add' | 'remove') => void;
}) => {
    // Use refs for drag start/mode so the global mouseup handler never goes stale.
    const dragStartRef = React.useRef<string | null>(null);
    const dragModeRef = React.useRef<'add' | 'remove'>('add');
    const dragPreviewRef = React.useRef<Set<string>>(new Set());
    // State drives re-renders for the visual preview.
    const [dragPreviewSet, setDragPreviewSet] = React.useState<Set<string>>(new Set());

    // Keep callback refs fresh so the mouseup handler never closes over a stale version.
    const onDateClickRef = React.useRef(onDateClick);
    const onDragSelectRef = React.useRef(onDragSelect);
    React.useEffect(() => {
        onDateClickRef.current = onDateClick;
        onDragSelectRef.current = onDragSelect;
    });

    const isDragging = dragPreviewSet.size > 0;

    const allDates = useMemo(
        () => calendarGrid.flat().filter(Boolean) as string[],
        [calendarGrid]
    );

    // Global mouseup: commit or cancel drag. Empty deps — stable via callback refs above.
    React.useEffect(() => {
        const handleMouseUp = () => {
            const start = dragStartRef.current;
            if (!start) return;
            const preview = dragPreviewRef.current;
            if (preview.size === 0) {
                // No movement — treat as a click.
                onDateClickRef.current(start);
            } else {
                onDragSelectRef.current(Array.from(preview), dragModeRef.current);
            }
            dragStartRef.current = null;
            dragPreviewRef.current = new Set();
            setDragPreviewSet(new Set());
        };
        window.addEventListener('mouseup', handleMouseUp);
        return () => window.removeEventListener('mouseup', handleMouseUp);
    }, []);

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
        <Box sx={{ width: '100%', overflowX: 'auto', pb: 1, userSelect: 'none' }}>
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
                            const inPreview = dragPreviewSet.has(dateStr);
                            const removeMode = dragModeRef.current === 'remove';

                            const dow = (dayjs(dateStr).day() + 6) % 7;
                            const month = dayjs(dateStr).month();
                            const cellMatch =
                                highlightedDows.has(dow) ||
                                highlightedDowMonthPairs.has(`${dow}:${month}`);

                            let bg: string;
                            let border: string;
                            if (inPreview) {
                                bg = removeMode ? 'rgba(239,68,68,0.55)' : 'rgba(22,162,152,0.65)';
                                border = removeMode
                                    ? '1px dashed rgba(239,68,68,0.9)'
                                    : '1px dashed rgba(22,162,152,0.9)';
                            } else if (sel) {
                                bg = `rgba(22,162,152,${0.15 + d * 0.65})`;
                                border = '1px solid transparent';
                            } else if (cellMatch) {
                                bg = d > 0
                                    ? `rgba(22,162,152,${0.22 + d * 0.55})`
                                    : 'rgba(22,162,152,0.12)';
                                border = '1px solid rgba(22,162,152,0.35)';
                            } else if (d > 0) {
                                bg = `rgba(147,51,234,${0.15 + d * 0.65})`;
                                border = '1px solid transparent';
                            } else {
                                bg = 'rgba(0,0,0,0.07)';
                                border = '1px solid transparent';
                            }

                            const boxProps = {
                                onMouseDown: (e: React.MouseEvent) => {
                                    e.preventDefault();
                                    dragStartRef.current = dateStr;
                                    dragModeRef.current = selectedDates.has(dateStr) ? 'remove' : 'add';
                                },
                                onMouseEnter: () => {
                                    if (!dragStartRef.current) return;
                                    if (dateStr === dragStartRef.current) {
                                        // Cursor returned to start — collapse preview so mouseup fires as a click.
                                        dragPreviewRef.current = new Set();
                                        setDragPreviewSet(new Set());
                                        return;
                                    }
                                    const start = dragStartRef.current;
                                    const [lo, hi] = start <= dateStr ? [start, dateStr] : [dateStr, start];
                                    const preview = new Set(allDates.filter((x) => x >= lo && x <= hi));
                                    dragPreviewRef.current = preview;
                                    setDragPreviewSet(preview);
                                },
                                sx: {
                                    width: CSIZ,
                                    height: CSIZ,
                                    bgcolor: bg,
                                    borderRadius: '2px',
                                    border,
                                    cursor: isDragging ? 'crosshair' : 'pointer',
                                    transition: isDragging ? 'none' : 'all 0.1s',
                                    '&:hover': isDragging ? {} : { filter: 'brightness(1.6)' },
                                },
                            };

                            if (isDragging) {
                                return <Box key={di} {...boxProps} />;
                            }
                            return (
                                <Tooltip
                                    key={di}
                                    title={dayjs(dateStr).format('ddd D MMM YYYY')}
                                    placement="top"
                                    arrow
                                >
                                    <Box {...boxProps} />
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

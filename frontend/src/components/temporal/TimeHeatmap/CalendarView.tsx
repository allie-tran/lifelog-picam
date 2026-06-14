import { Box, Tooltip, Typography } from '@mui/material';
import dayjs from 'dayjs';
import React, { useMemo } from 'react';
import { CSIZ, CGAP, MONTH_ABBR } from './constants';

const CalendarView = ({
    calendarGrid,
    density,
    selectedDates,
    highlightedDows,
    highlightedDowMonthPairs,
    onDateClick,
    onDragSelect,
    showDowLabels = true,
}: {
    calendarGrid: (string | null)[][];
    density: (number | null)[][];
    selectedDates: Set<string>;
    highlightedDows: Set<number>;
    highlightedDowMonthPairs: Set<string>;
    onDateClick: (d: string) => void;
    onDragSelect: (dates: string[], mode: 'add' | 'remove') => void;
    showDowLabels?: boolean;
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
            <Box
                sx={{
                    position: 'relative',
                    height: 14,
                    ml: `${showDowLabels ? CSIZ + CGAP + 6 : 6}px`,
                }}
            >
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
                {/* Day-of-week labels (M W F S) — meaningless once days span many
                    years continuously (All view), so hidden there. */}
                {showDowLabels && (
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
                )}

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

export default React.memo(CalendarView);

import { Box, Tooltip, Typography } from '@mui/material';
import React, { memo, useState } from 'react';
import { ROW_LABEL_W, CELL_H } from './constants';

type RowItem = { key: string; label: string; sub: string; tip?: string };

const GridView = ({
    rowItems,
    colLabels,
    selectedRows,
    selectedCols,
    density,
    counts,
    rowTotals,
    colTotals,
    unit = 'images',
    onRowClick,
    onColClick,
    onCellClick,
    onRangeSelect,
    cellH = CELL_H,
}: {
    rowItems: RowItem[];
    colLabels: string[];
    selectedRows: number[];
    selectedCols: number[];
    density: number[][];
    counts: number[][];
    rowTotals?: number[];
    colTotals?: number[];
    unit?: string;
    onRowClick: (i: number) => void;
    onColClick: (i: number) => void;
    onCellClick: (ri: number, ci: number) => void;
    onRangeSelect?: (rows: number[], cols: number[]) => void;
    cellH?: number;
}) => {
    const [hovered, setHovered] = useState<{ ri: number; ci: number } | null>(null);

    // Drag-select: refs hold the live drag span so the global mouseup never
    // closes over stale state; a state copy drives the preview re-render.
    const dragStartRef = React.useRef<{ ri: number; ci: number } | null>(null);
    const dragRectRef = React.useRef<{ rows: number[]; cols: number[] } | null>(null);
    const [dragRect, setDragRect] = useState<{ rows: number[]; cols: number[] } | null>(null);

    // Keep callbacks fresh for the empty-deps mouseup listener.
    const onCellClickRef = React.useRef(onCellClick);
    const onRangeSelectRef = React.useRef(onRangeSelect);
    React.useEffect(() => {
        onCellClickRef.current = onCellClick;
        onRangeSelectRef.current = onRangeSelect;
    });

    React.useEffect(() => {
        const handleMouseUp = () => {
            const start = dragStartRef.current;
            if (!start) return;
            const rect = dragRectRef.current;
            if (!rect || (rect.rows.length <= 1 && rect.cols.length <= 1)) {
                // No movement — treat as a single-cell click.
                onCellClickRef.current(start.ri, start.ci);
            } else {
                onRangeSelectRef.current?.(rect.rows, rect.cols);
            }
            dragStartRef.current = null;
            dragRectRef.current = null;
            setDragRect(null);
        };
        window.addEventListener('mouseup', handleMouseUp);
        return () => window.removeEventListener('mouseup', handleMouseUp);
    }, []);

    const isDragging = dragRect !== null;

    const range = (a: number, b: number) => {
        const lo = Math.min(a, b);
        const hi = Math.max(a, b);
        return Array.from({ length: hi - lo + 1 }, (_, i) => lo + i);
    };

    const inPreview = (ri: number, ci: number) =>
        dragRect !== null && dragRect.rows.includes(ri) && dragRect.cols.includes(ci);

    const rowName = (it: RowItem) => it.tip ?? it.label ?? it.key;

    return (
        <Box sx={{ display: 'flex', flexDirection: 'column', width: '100%', userSelect: 'none' }}>
            {/* Column headers */}
            <Box sx={{ display: 'flex', ml: `${ROW_LABEL_W}px` }}>
                {colLabels.map((label, ci) => {
                    const active = selectedCols.includes(ci);
                    const hovering = hovered?.ci === ci;
                    const header = (
                        <Box
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
                    return colTotals ? (
                        <Tooltip key={ci} title={`${label} — ${colTotals[ci] ?? 0} ${unit}`} placement="top" arrow>
                            {header}
                        </Tooltip>
                    ) : (
                        <React.Fragment key={ci}>{header}</React.Fragment>
                    );
                })}
            </Box>

            {/* Rows */}
            {rowItems.map((item, ri) => {
                const { label, sub } = item;
                const rowActive = selectedRows.includes(ri);
                const rowHovering = hovered?.ri === ri;
                const rowLabelBox = (
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
                );
                return (
                    <Box key={ri} sx={{ display: 'flex', alignItems: 'stretch', mb: '2px' }}>
                        {/* Row label */}
                        {rowTotals ? (
                            <Tooltip title={`${rowName(item)} — ${rowTotals[ri] ?? 0} ${unit}`} placement="right" arrow>
                                {rowLabelBox}
                            </Tooltip>
                        ) : (
                            rowLabelBox
                        )}

                        {/* Cells */}
                        {colLabels.map((colLabel, ci) => {
                            const colActive = selectedCols.includes(ci);
                            const isHovered = hovered?.ri === ri && hovered?.ci === ci;
                            const rowOrColHovered = hovered?.ri === ri || hovered?.ci === ci;
                            const previewing = inPreview(ri, ci);
                            const d = density[ri]?.[ci] ?? 0;
                            const c = counts[ri]?.[ci] ?? 0;
                            let bg: string;
                            if (previewing) {
                                bg = `rgba(22,162,152,${0.4 + d * 0.4})`;
                            } else if (rowActive && colActive) {
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
                            const cell = (
                                <Box
                                    onMouseDown={(e) => {
                                        e.preventDefault();
                                        dragStartRef.current = { ri, ci };
                                        dragRectRef.current = { rows: [ri], cols: [ci] };
                                        setDragRect({ rows: [ri], cols: [ci] });
                                    }}
                                    onMouseEnter={() => {
                                        setHovered({ ri, ci });
                                        const start = dragStartRef.current;
                                        if (!start) return;
                                        const rect = {
                                            rows: range(start.ri, ri),
                                            cols: range(start.ci, ci),
                                        };
                                        dragRectRef.current = rect;
                                        setDragRect(rect);
                                    }}
                                    onMouseLeave={() => setHovered(null)}
                                    sx={{
                                        flex: 1,
                                        height: cellH,
                                        bgcolor: bg,
                                        m: '1px',
                                        borderRadius: '4px',
                                        border: previewing
                                            ? '1px dashed rgba(22,162,152,0.9)'
                                            : isHovered
                                                ? '1px solid rgba(22,162,152,0.5)'
                                                : '1px solid rgba(255,255,255,0.12)',
                                        cursor: isDragging ? 'crosshair' : 'pointer',
                                        transition: isDragging ? 'none' : 'all 0.1s',
                                    }}
                                />
                            );
                            if (isDragging) {
                                return <React.Fragment key={ci}>{cell}</React.Fragment>;
                            }
                            return (
                                <Tooltip
                                    key={ci}
                                    title={`${rowName(item)} · ${colLabel} — ${c} ${unit}`}
                                    placement="top"
                                    arrow
                                    disableInteractive
                                >
                                    {cell}
                                </Tooltip>
                            );
                        })}
                    </Box>
                );
            })}
        </Box>
    );
};

export default memo(GridView);

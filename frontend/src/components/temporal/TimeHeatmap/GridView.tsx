import { Box, Typography } from '@mui/material';
import { useState } from 'react';
import { ROW_LABEL_W, CELL_H } from './constants';

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

export default GridView;

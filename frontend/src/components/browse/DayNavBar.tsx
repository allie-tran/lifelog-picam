import { Box, Tooltip, Typography } from '@mui/material';
import { CATEGORIES, THEME_COLORS } from 'constants/activityColors';
import dayjs from 'dayjs';
import { useState } from 'react';
import { NavSegment } from 'apis/browsing';

export type SegmentSelection = number | number[] | 'unsegmented';

interface DayNavBarProps {
    navSegments: NavSegment[] | undefined;
    selectedSegmentId: SegmentSelection | null;
    onSelectSegment: (id: SegmentSelection) => void;
    hasRecent?: boolean;
}

function fmtDuration(totalSeconds: number): string {
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    if (h > 0) return m > 0 ? `${h}h ${m}m` : `${h}h`;
    return `${m}m`;
}

type LocationRun = {
    name: string | null;
    startMs: number;
    endMs: number;
    totalSeconds: number;
    segments: NavSegment[];
    isMove: boolean;
};

function buildLocationRuns(segments: NavSegment[]): LocationRun[] {
    const runs: LocationRun[] = [];
    for (const seg of segments) {
        const loc = seg.locationName ?? null;
        const last = runs[runs.length - 1];
        if (last && last.name === loc) {
            last.endMs = dayjs(seg.endTime).valueOf();
            last.totalSeconds += seg.duration;
            last.segments.push(seg);
        } else {
            runs.push({
                name: loc,
                startMs: dayjs(seg.startTime).valueOf(),
                endMs: dayjs(seg.endTime).valueOf(),
                totalSeconds: seg.duration,
                segments: [seg],
                isMove: false,
            });
        }
    }
    for (const run of runs) {
        run.isMove = run.segments.some(
            (s) => (s.locationName ?? '').includes('→')
        );
    }
    return runs;
}

const MOVE_BG = '#9575cd20';

// Match map pill color scale (count estimated from duration at 10s/image)
function stopColour(totalSeconds: number): string {
    const count = totalSeconds / 10;
    if (count >= 100) return '#ef9a9a';   // red  — matches map large
    if (count >= 40)  return '#ffcc80';   // amber — matches map medium
    return '#90caf9';                      // blue  — matches map small
}

export default function DayNavBar({ navSegments, selectedSegmentId, onSelectSegment, hasRecent = false }: DayNavBarProps) {
    const [activeRunIdx, setActiveRunIdx] = useState<number | null>(null);

    const segments: NavSegment[] = navSegments ?? [];
    if (!segments.length) return null;

    const totalStart = dayjs(segments[0].startTime).valueOf();
    const totalEnd = dayjs(segments[segments.length - 1].endTime).valueOf();
    const totalSpan = totalEnd - totalStart || 1;

    const widthPct = (startMs: number, endMs: number) =>
        ((endMs - startMs) / totalSpan) * 100;

    const locationRuns = buildLocationRuns(segments);

    return (
        <Box sx={{ width: '100%', mb: 1 }}>
            <Box sx={{ display: 'flex', width: '100%', overflow: 'hidden' }}>
                {locationRuns.map((run, ri) => {
                    const w = run.segments.reduce((sum, seg) =>
                        sum + widthPct(dayjs(seg.startTime).valueOf(), dayjs(seg.endTime).valueOf()), 0);
                    const isActive = activeRunIdx === ri;
                    const bg = run.isMove ? MOVE_BG : stopColour(run.totalSeconds);

                    // Relative widths of segments within this run (normalize to fill the cell)
                    const runTotalMs = run.segments.reduce((sum, seg) =>
                        sum + (dayjs(seg.endTime).valueOf() - dayjs(seg.startTime).valueOf()), 0) || 1;

                    return (
                        <Box
                            key={ri}
                            sx={{
                                flexBasis: 24,
                                flexGrow: w,
                                flexShrink: 0,
                                display: 'flex',
                                flexDirection: 'column',
                                opacity:
                                    selectedSegmentId === 'unsegmented'
                                        ? 0.35
                                        : activeRunIdx !== null && !isActive
                                          ? 0.35
                                          : 1,
                                transition: 'opacity 0.15s',
                                overflow: 'hidden',
                            }}
                        >
                            {/* Location header */}
                            <Tooltip
                                title={`📍 ${run.name ?? 'Unknown'} · ${dayjs(run.startMs).format('HH:mm')}–${dayjs(run.endMs).format('HH:mm')} · ${fmtDuration(run.totalSeconds)}`}
                                followCursor
                            >
                                <Box
                                    onClick={() => {
                                        let count = 0;
                                        const ids: number[] = [];
                                        for (const seg of run.segments) {
                                            if (seg.segmentId == null) continue;
                                            ids.push(seg.segmentId);
                                            count += Math.ceil(seg.duration / 10);
                                            if (count >= 100) break;
                                        }
                                        setActiveRunIdx((x) => x === ri ? null : ri);
                                        if (ids.length) onSelectSegment(ids.length === 1 ? ids[0] : ids);
                                    }}
                                    sx={{
                                        height: 44,
                                        bgcolor: bg,
                                        cursor: 'pointer',
                                        overflow: 'hidden',
                                        display: 'flex',
                                        flexDirection: 'column',
                                        justifyContent: 'center',
                                        mb: '2px',
                                        p: '0 4px',
                                        border: '1px solid white',
                                        borderRadius: '4px',
                                    }}
                                >
                                    <Typography variant="caption" fontWeight={700} noWrap sx={{ lineHeight: 1.2, color: '#fff' }}>
                                        {run.isMove ? 'In transit' : (run.name ?? '—')}
                                    </Typography>
                                    <Typography variant="caption" noWrap sx={{ fontSize: '0.65rem', lineHeight: 1.2, color: 'rgba(255,255,255,0.8)' }}>
                                        {fmtDuration(run.totalSeconds)}
                                    </Typography>
                                </Box>
                            </Tooltip>

                            {/* Activity cells — fill this run's width */}
                            <Box sx={{ display: 'flex', height: 36, border: '1px solid #fff', borderRadius: '4px', overflow: 'hidden' }}>
                                {run.segments.map((seg, si) => {
                                    const segMs = dayjs(seg.endTime).valueOf() - dayjs(seg.startTime).valueOf();
                                    const segRelW = (segMs / runTotalMs) * 100;
                                    const isLastSeg = si === run.segments.length - 1;
                                    const color =
                                        THEME_COLORS[seg.activityGroup] ||
                                        CATEGORIES[seg.activity] ||
                                        '#e0e0e0';
                                    const isSelected = Array.isArray(selectedSegmentId)
                                        ? seg.segmentId != null && selectedSegmentId.includes(seg.segmentId)
                                        : selectedSegmentId === seg.segmentId;
                                    return (
                                        <Tooltip
                                            key={seg.segmentId ?? si}
                                            title={`${seg.activity} · ${dayjs(seg.startTime).format('HH:mm')}–${dayjs(seg.endTime).format('HH:mm')}`}
                                            followCursor
                                        >
                                            <Box
                                                onClick={() => seg.segmentId != null && onSelectSegment(seg.segmentId)}
                                                sx={{
                                                    flexBasis: `${segRelW}%`,
                                                    flexGrow: isLastSeg ? 1 : 0,
                                                    flexShrink: 1,
                                                    minWidth: 0,
                                                    height: '100%',
                                                    bgcolor: color,
                                                    cursor: seg.segmentId != null ? 'pointer' : 'default',
                                                    boxShadow: isSelected ? 'inset 0 0 0 2px rgba(0,0,0,0.4)' : 'none',
                                                    transition: 'box-shadow 0.1s',
                                                    '&:hover': seg.segmentId != null ? { filter: 'brightness(0.88)' } : {},
                                                    borderLeft: si > 0 ? '1px solid #fff' : 'none',
                                                }}
                                            />
                                        </Tooltip>
                                    );
                                })}
                            </Box>
                        </Box>
                    );
                })}

                {/* Recent — newest images not yet grouped; appended last */}
                {hasRecent && (
                    <Tooltip title="Recent — newest images not yet grouped" followCursor>
                        <Box
                            onClick={() => {
                                setActiveRunIdx(null);
                                onSelectSegment('unsegmented');
                            }}
                            sx={{
                                flexBasis: 70,
                                flexGrow: 0,
                                flexShrink: 0,
                                ml: '4px',
                                height: 82,
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                bgcolor: '#26a69a',
                                color: '#fff',
                                cursor: 'pointer',
                                border: '1px solid white',
                                borderRadius: '4px',
                                opacity: selectedSegmentId === 'unsegmented' ? 1 : 0.6,
                                boxShadow:
                                    selectedSegmentId === 'unsegmented'
                                        ? 'inset 0 0 0 2px rgba(0,0,0,0.4)'
                                        : 'none',
                                transition: 'opacity 0.15s, box-shadow 0.1s',
                            }}
                        >
                            <Typography variant="caption" fontWeight={700} noWrap sx={{ lineHeight: 1.2 }}>
                                Recent
                            </Typography>
                        </Box>
                    </Tooltip>
                )}
            </Box>

            {/* Time labels */}
            {(() => {
                const spanH = (totalEnd - totalStart) / 3_600_000;
                const stepH = spanH < 6 ? 0.5 : spanH < 12 ? 1 : 2;
                const first = dayjs(totalStart).startOf('hour').add(stepH, 'hour');
                const ticks: { pct: number; label: string }[] = [];
                let t = first;
                while (t.valueOf() < totalEnd) {
                    const pct = (t.valueOf() - totalStart) / totalSpan * 100;
                    if (pct > 1 && pct < 99) ticks.push({ pct, label: t.format('HH:mm') });
                    t = t.add(stepH, 'hour');
                }
                return (
                    <Box sx={{ position: 'relative', height: 16, mt: '3px', userSelect: 'none' }}>
                        <Typography variant="caption" color="text.secondary"
                            sx={{ position: 'absolute', left: 0, transform: 'none' }}>
                            {dayjs(segments[0].startTime).format('HH:mm')}
                        </Typography>
                        {ticks.map((tick, i) => (
                            <Typography key={i} variant="caption" color="text.secondary"
                                sx={{ position: 'absolute', left: `${tick.pct}%`, transform: 'translateX(-50%)' }}>
                                {tick.label}
                            </Typography>
                        ))}
                        <Typography variant="caption" color="text.secondary"
                            sx={{ position: 'absolute', right: 0 }}>
                            {dayjs(segments[segments.length - 1].endTime).format('HH:mm')}
                        </Typography>
                    </Box>
                );
            })()}

        </Box>
    );
}

import { Box, Tooltip, Typography } from '@mui/material';
import { CATEGORIES, THEME_COLORS } from 'constants/activityColors';
import { colorForPlace } from 'utils/placeColors';
import dayjs from 'dayjs';
import { useState } from 'react';
import { NavSegment } from 'apis/browsing';

export type SegmentSelection = number | number[] | 'unsegmented';

interface DayNavBarProps {
    navSegments: NavSegment[] | undefined;
    selectedSegmentId: SegmentSelection | null;
    viewingSegmentId?: number | null;
    onSelectSegment: (id: SegmentSelection) => void;
    hasRecent?: boolean;
}

function fmtDuration(totalSeconds: number): string {
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    if (h > 0) return m > 0 ? `${h}h ${m}m` : `${h}h`;
    return `${m}m`;
}

// Transport-mode → emoji (from ImageGPS.mode). 'stationary'/null → no icon.
const MODE_ICON: Record<string, string> = {
    flight: '✈️',
    car: '🚗',
    vehicle: '🚗',
    public_transport: '🚌',
    train: '🚆',
    walk: '🚶',
    cycle: '🚴',
    stationary: '🚶',
};

// User location label kind → emoji.
const LABEL_ICON: Record<string, string> = {
    home: '🏠',
    work: '💼',
};

function modal<T>(items: T[]): T | null {
    if (!items.length) return null;
    const counts = new Map<T, number>();
    for (const it of items) counts.set(it, (counts.get(it) ?? 0) + 1);
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1])[0][0];
}

// Header label + tooltip text for a location run (transit vs. place, with icons).
function runHeader(run: LocationRun): { headerText: string; tipTitle: string } {
    const modeIcon = run.mode ? MODE_ICON[run.mode] ?? '' : '';
    const labelIcon = run.labelKind ? LABEL_ICON[run.labelKind] ?? '' : '';
    const headerText = run.isMove
        ? `${modeIcon}`.trim()
        : `${labelIcon} ${run.name ?? '—'}`.trim();
    const tipBits = [
        run.isMove ? `${modeIcon} ${run.mode}` : `📍 ${run.name ?? 'Unknown'}`,
        `${dayjs(run.startMs).format('HH:mm')}–${dayjs(run.endMs).format('HH:mm')}`,
        fmtDuration(run.totalSeconds),
    ];
    if (run.mode && !run.isMove) tipBits.push(`${modeIcon} ${run.mode}`.trim());
    return { headerText, tipTitle: tipBits.join(' · ') };
}

type LocationRun = {
    name: string | null;
    startMs: number;
    endMs: number;
    totalSeconds: number;
    segments: NavSegment[];
    isMove: boolean;
    mode: string | null;
    labelKind: string | null;
};

function buildLocationRuns(segments: NavSegment[]): LocationRun[] {
    const runs: LocationRun[] = [];
    for (const seg of segments) {
        const loc = seg.locationName ?? null;
        const mode = seg.mode ?? null;
        const last = runs[runs.length - 1];
        if (last && last.name === loc && last.mode === mode) {
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
                mode: mode,
                labelKind: null,
            });
        }
    }
    for (const run of runs) {
        run.isMove = run.segments.some(
            (s) => (s.locationName ?? '').includes('→')
        );
        run.mode = modal(run.segments.map((s) => s.mode).filter(Boolean) as string[]);
        // labelKind isn't modal: a single home/work label anywhere in the run
        // wins (a labeled place dominates over its unlabeled neighbour segments).
        run.labelKind =
            run.segments.map((s) => s.labelKind).find((k) => k === 'home' || k === 'work') ?? null;
    }
    return runs;
}

const MOVE_BG = '#9575cd20';

const segColor = (seg: NavSegment) =>
    THEME_COLORS[seg.activityGroup] || CATEGORIES[seg.activity] || '#e0e0e0';

export default function DayNavBar({ navSegments, selectedSegmentId, viewingSegmentId = null, onSelectSegment, hasRecent = false }: DayNavBarProps) {
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
                    const bg = run.isMove ? MOVE_BG : colorForPlace(run.name);

                    // Relative widths of segments within this run (normalize to fill the cell)
                    const runTotalMs = run.segments.reduce((sum, seg) =>
                        sum + (dayjs(seg.endTime).valueOf() - dayjs(seg.startTime).valueOf()), 0) || 1;
                    const header = runHeader(run);
                    return (
                        <Box
                            key={ri}
                            sx={{
                                flexBasis: 16,
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
                                title={header.tipTitle}
                                followCursor
                            >
                                <Box
                                    onClick={() => {
                                        const ids = run.segments
                                            .map((s) => s.segmentId)
                                            .filter((id): id is number => id != null);
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
                                        {header.headerText}
                                    </Typography>
                                    <Typography variant="caption" noWrap sx={{ fontSize: '0.65rem', lineHeight: 1.2, color: 'rgba(255,255,255,0.8)' }}>
                                        {fmtDuration(run.totalSeconds)}
                                    </Typography>
                                </Box>
                            </Tooltip>

                            {/* Activity cells — one per segment */}
                            <Box sx={{ display: 'flex', height: 36, border: '1px solid #fff', borderRadius: '4px', overflow: 'hidden' }}>
                                {run.segments.map((seg, si) => {
                                    const segMs = dayjs(seg.endTime).valueOf() - dayjs(seg.startTime).valueOf();
                                    const segRelW = (segMs / runTotalMs) * 100;
                                    const isLastSeg = si === run.segments.length - 1;
                                    const background = segColor(seg);
                                    const clickable = seg.segmentId != null;
                                    const isSelected = Array.isArray(selectedSegmentId)
                                        ? seg.segmentId != null && selectedSegmentId.includes(seg.segmentId)
                                        : selectedSegmentId === seg.segmentId;
                                    const isViewing =
                                        viewingSegmentId != null && seg.segmentId === viewingSegmentId;
                                    const range = `${dayjs(seg.startTime).format('HH:mm')}–${dayjs(seg.endTime).format('HH:mm')}`;
                                    const title = `${seg.activity} · ${range}`;
                                    return (
                                        <Tooltip key={seg.segmentId ?? si} title={title} followCursor>
                                            <Box
                                                onClick={() => {
                                                    if (seg.segmentId != null) onSelectSegment(seg.segmentId);
                                                }}
                                                sx={{
                                                    flexBasis: `${segRelW}%`,
                                                    flexGrow: isLastSeg ? 1 : 0,
                                                    flexShrink: 1,
                                                    minWidth: 0,
                                                    height: '100%',
                                                    background,
                                                    cursor: clickable ? 'pointer' : 'default',
                                                    boxShadow: isViewing
                                                        ? 'inset 0 0 0 3px #1565c0'
                                                        : isSelected
                                                          ? 'inset 0 0 0 2px rgba(0,0,0,0.4)'
                                                          : 'none',
                                                    zIndex: isViewing ? 1 : 0,
                                                    transition: 'box-shadow 0.1s',
                                                    '&:hover': clickable ? { filter: 'brightness(0.88)' } : {},
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

import { Box, Tooltip, Typography } from '@mui/material';
import { CATEGORIES, THEME_COLORS } from 'constants/activityColors';
import { colorForPlace } from 'utils/placeColors';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';
import { Fragment, useState } from 'react';
import { NavSegment } from 'apis/browsing';

dayjs.extend(utc);
dayjs.extend(timezone);

// Segment times arrive as naive UTC. Parse them as UTC so epoch math is correct
// regardless of the browser zone, and format for display in the *capture* zone
// (the segment's own timezone) so the bar reads local wall-clock, not UTC.
const uMs = (t: string) => dayjs.utc(t).valueOf();
const hm = (ms: number, tz?: string | null) =>
    (tz ? dayjs(ms).tz(tz) : dayjs.utc(ms)).format('HH:mm');

// Gaps between consecutive location runs longer than this are recording breaks:
// runs otherwise pack edge-to-edge and the gap vanishes. Collapse to a labeled
// marker so a break is visible without a long gap squishing the activity bars.
const BREAK_THRESHOLD_MS = 15 * 60 * 1000;

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

// Clock-aligned 3-hour ticks (…, 09:00, 12:00, …) inside one run's time span,
// positioned as a percentage. Time is linear within a run, so pct is exact.
const TICK_STEP_H = 3;
function runTicks(startMs: number, endMs: number, tz?: string | null): { pct: number; label: string }[] {
    const spanMs = endMs - startMs;
    if (spanMs <= 0) return [];
    const ticks: { pct: number; label: string }[] = [];
    // Clock-align in the capture zone so ticks land on local 09:00/12:00/…
    let t = (tz ? dayjs(startMs).tz(tz) : dayjs.utc(startMs)).startOf('hour');
    while (t.valueOf() <= startMs || t.hour() % TICK_STEP_H !== 0) t = t.add(1, 'hour');
    while (t.valueOf() < endMs) {
        const pct = ((t.valueOf() - startMs) / spanMs) * 100;
        if (pct > 2 && pct < 98) ticks.push({ pct, label: t.format('HH:mm') });
        t = t.add(TICK_STEP_H, 'hour');
    }
    return ticks;
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
        `${hm(run.startMs, run.tz)}–${hm(run.endMs, run.tz)}`,
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
    tz: string | null;
};

function buildLocationRuns(segments: NavSegment[]): LocationRun[] {
    const runs: LocationRun[] = [];
    for (const seg of segments) {
        const loc = seg.locationName ?? null;
        const mode = seg.mode ?? null;
        const last = runs[runs.length - 1];
        // A recording break splits a run even at the same location (e.g. home →
        // camera off over lunch → home) so the gap gets its own break marker.
        const gapMs = last ? uMs(seg.startTime) - last.endMs : 0;
        if (last && last.name === loc && gapMs < BREAK_THRESHOLD_MS) {
            last.endMs = uMs(seg.endTime);
            last.totalSeconds += seg.duration;
            last.segments.push(seg);
        } else {
            runs.push({
                name: loc,
                startMs: uMs(seg.startTime),
                endMs: uMs(seg.endTime),
                totalSeconds: seg.duration,
                segments: [seg],
                isMove: false,
                mode: mode,
                labelKind: null,
                tz: seg.timezone ?? null,
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

    const totalStart = uMs(segments[0].startTime);
    const totalEnd = uMs(segments[segments.length - 1].endTime);
    const totalSpan = totalEnd - totalStart || 1;

    const widthPct = (startMs: number, endMs: number) =>
        ((endMs - startMs) / totalSpan) * 100;

    const locationRuns = buildLocationRuns(segments);

    return (
        <Box sx={{ width: '100%', mb: 1 }}>
            <Box sx={{ display: 'flex', width: '100%', overflow: 'hidden' }}>
                {locationRuns.map((run, ri) => {
                    const w = run.segments.reduce((sum, seg) =>
                        sum + widthPct(uMs(seg.startTime), uMs(seg.endTime)), 0);
                    const isActive = activeRunIdx === ri;
                    const bg = run.isMove ? MOVE_BG : colorForPlace(run.name);

                    // Relative widths of segments within this run (normalize to fill the cell)
                    const runTotalMs = run.segments.reduce((sum, seg) =>
                        sum + (uMs(seg.endTime) - uMs(seg.startTime)), 0) || 1;
                    const header = runHeader(run);
                    const gapMs = ri > 0 ? run.startMs - locationRuns[ri - 1].endMs : 0;
                    const showBreak = ri > 0 && gapMs >= BREAK_THRESHOLD_MS;
                    return (
                        <Fragment key={ri}>
                        {showBreak && (
                            <Tooltip
                                title={`No recording · ${hm(locationRuns[ri - 1].endMs, locationRuns[ri - 1].tz)}–${hm(run.startMs, run.tz)} · ${fmtDuration(gapMs / 1000)}`}
                                followCursor
                            >
                                <Box
                                    sx={{
                                        flex: '0 0 auto',
                                        width: 46,
                                        alignSelf: 'stretch',
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'center',
                                        mx: '2px',
                                        borderLeft: '1px dashed',
                                        borderRight: '1px dashed',
                                        borderColor: 'divider',
                                    }}
                                >
                                    <Typography
                                        variant="caption"
                                        color="text.disabled"
                                        sx={{ fontSize: 9, whiteSpace: 'nowrap' }}
                                    >
                                        ┈ {fmtDuration(gapMs / 1000)} ┈
                                    </Typography>
                                </Box>
                            </Tooltip>
                        )}
                        <Box
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
                                    const segMs = uMs(seg.endTime) - uMs(seg.startTime);
                                    const segRelW = (segMs / runTotalMs) * 100;
                                    const isLastSeg = si === run.segments.length - 1;
                                    const background = segColor(seg);
                                    const clickable = seg.segmentId != null;
                                    const isSelected = Array.isArray(selectedSegmentId)
                                        ? seg.segmentId != null && selectedSegmentId.includes(seg.segmentId)
                                        : selectedSegmentId === seg.segmentId;
                                    const isViewing =
                                        viewingSegmentId != null && seg.segmentId === viewingSegmentId;
                                    const range = `${hm(uMs(seg.startTime), run.tz)}–${hm(uMs(seg.endTime), run.tz)}`;
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
                        </Fragment>
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

            {/* Time labels — a tick every 3h within each run, plus the resume time
                at the start of a run that follows a recording break. Mirrors the bar
                layout (incl. break spacers) so ticks sit under their location. */}
            <Box sx={{ display: 'flex', width: '100%', mt: '3px', userSelect: 'none' }}>
                {locationRuns.map((run, ri) => {
                    const w = run.segments.reduce((sum, seg) =>
                        sum + widthPct(uMs(seg.startTime), uMs(seg.endTime)), 0);
                    const gapBefore = ri > 0 ? run.startMs - locationRuns[ri - 1].endMs : 0;
                    const showBreak = ri > 0 && gapBefore >= BREAK_THRESHOLD_MS;
                    const gapAfter = ri < locationRuns.length - 1 ? locationRuns[ri + 1].startMs - run.endMs : 0;
                    const showStop = gapAfter >= BREAK_THRESHOLD_MS;
                    const ticks = runTicks(run.startMs, run.endMs, run.tz);
                    return (
                        <Fragment key={ri}>
                            {showBreak && <Box sx={{ flex: '0 0 auto', width: 46, mx: '2px' }} />}
                            <Box
                                sx={{
                                    flexBasis: 16,
                                    flexGrow: w,
                                    flexShrink: 0,
                                    minWidth: 0,
                                    position: 'relative',
                                    height: 16,
                                }}
                            >
                                {showBreak && (
                                    <Typography variant="caption" color="text.secondary" noWrap
                                        sx={{ position: 'absolute', left: 0, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                                        {hm(run.startMs, run.tz)}
                                    </Typography>
                                )}
                                {ticks.map((tick) => (
                                    <Typography key={tick.label} variant="caption" color="text.secondary" noWrap
                                        sx={{ position: 'absolute', left: `${tick.pct}%`, transform: 'translateX(-50%)', fontVariantNumeric: 'tabular-nums' }}>
                                        {tick.label}
                                    </Typography>
                                ))}
                                {showStop && (
                                    <Typography variant="caption" color="text.secondary" noWrap
                                        sx={{ position: 'absolute', right: 0, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                                        {hm(run.endMs, run.tz)}
                                    </Typography>
                                )}
                            </Box>
                        </Fragment>
                    );
                })}
                {hasRecent && <Box sx={{ flex: '0 0 auto', width: 70, ml: '4px' }} />}
            </Box>

        </Box>
    );
}

import { Box, IconButton, Tooltip, Typography } from '@mui/material';
import EditLocationAltIcon from '@mui/icons-material/EditLocationAlt';
import { CATEGORIES, THEME_COLORS } from 'constants/activityColors';
import { colorForPlace } from 'utils/placeColors';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';
import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import { NavSegment } from 'apis/browsing';
import StopCorrectionDialog from 'components/browse/StopCorrectionDialog';

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
    device?: string;
    date?: string;
    // Called after a manual stop-venue correction so the parent can refresh.
    onLocationCorrected?: () => void;
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
    bus: '🚌',
    tram: '🚊',
    train: '🚆',
    subway: '🚇',
    ferry: '⛴️',
    cable_car: '🚡',
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

// A short stationary run (≤ this) between moves is a transit waypoint (a bus/tram
// stop, a platform wait), not a destination. Mirrors location_visits._WAIT_MAX_S.
const WAIT_MAX_S = 3 * 60;

// Header label + tooltip text for a location run (transit vs. place, with icons).
function runHeader(run: LocationRun): { headerText: string; tipTitle: string } {
    const modeIcon = run.mode ? MODE_ICON[run.mode] ?? '' : '';
    const labelIcon = run.labelKind ? LABEL_ICON[run.labelKind] ?? '' : '';
    const headerText = run.isMove
        ? `${modeIcon}`.trim()
        : `${labelIcon} ${run.name ?? '—'}`.trim();
    // For a move show its route (e.g. "Pfauen → Garbenstrasse"), falling back to
    // the transport mode; for a place show the venue name.
    const moveLabel = run.name && run.name.includes('→') ? run.name : run.mode ?? 'transit';
    const tipBits = [
        run.isMove ? `${modeIcon} ${moveLabel}`.trim() : `📍 ${run.name ?? 'Unknown'}`,
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
        // Same location stays one run even across a recording break (e.g. home →
        // camera off over lunch → home): the header spans continuously and the
        // gap is drawn only in the activity row. A location *change* is what
        // splits runs, so a full break marker appears there instead.
        if (last && last.name === loc) {
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
    // Fold short transfer stops into the journey so one ride reads as one run,
    // matching the day-summary visits (location_visits._merge_transit_waypoints).
    const folded = mergeTransitWaypoints(runs);
    // Collapse consecutive GPS-only (no-photo) segments in a run into one cell,
    // so a stay split into several imageless stops reads as a single "no photos"
    // block rather than a row of tiny cells with gaps between.
    return folded.map((run) => ({ ...run, segments: collapseGpsOnly(run.segments) }));
}

// Merge back-to-back image-less segments (segmentId == null) — all at the same
// location within a run — into one spanning segment. Non-null (photo) segments
// pass through untouched. Segments are cloned so the source array is untouched.
function collapseGpsOnly(segs: NavSegment[]): NavSegment[] {
    const out: NavSegment[] = [];
    for (const seg of segs) {
        const last = out[out.length - 1];
        if (seg.segmentId == null && last && last.segmentId == null) {
            last.endTime = seg.endTime;
            last.duration += seg.duration;
        } else {
            out.push({ ...seg });
        }
    }
    return out;
}

// ── Transit-waypoint folding (ported from location_visits.py) ────────────────
type RunKind = 'real_stop' | 'transit' | 'short_stop';

const runStationarySeconds = (run: LocationRun): number =>
    run.segments.reduce((s, seg) => s + (seg.locationStop === true ? seg.duration : 0), 0);

function runKind(run: LocationRun): RunKind {
    if (runStationarySeconds(run) > WAIT_MAX_S) return 'real_stop';
    if (run.isMove) return 'transit';
    return 'short_stop';
}

// Route label from a merged journey's segments: origin → destination taken from
// its 'A → B' move names (first origin, last destination).
function journeyName(segs: NavSegment[]): string {
    const arrows = segs.map((s) => s.locationName ?? '').filter((n) => n.includes('→'));
    if (arrows.length) {
        const origin = arrows[0].split('→')[0].trim();
        const dest = (arrows[arrows.length - 1].split('→').pop() ?? '').trim();
        if (origin && dest) return origin !== dest ? `${origin} → ${dest}` : origin;
    }
    const named = segs.map((s) => s.locationName ?? '').find((n) => n && !n.includes('→'));
    return named || 'In transit';
}

// Split a transit core into contiguous same-mode legs. A waypoint stop (no mode)
// that sits just before a mode change is attached to the upcoming leg (you wait,
// then board), so "walk → wait → bus" splits as [walk] [wait+bus].
function splitByMode(runs: LocationRun[]): LocationRun[][] {
    const chunks: LocationRun[][] = [];
    let cur: LocationRun[] = [];
    let curMode: string | null = null;
    for (let k = 0; k < runs.length; k++) {
        const r = runs[k];
        const m = r.isMove ? r.mode : null;
        if (m === null && cur.length && curMode !== null) {
            const nextMove = runs.slice(k + 1).find((x) => x.isMove);
            if (nextMove && nextMove.mode && nextMove.mode !== curMode) {
                chunks.push(cur);
                cur = [];
                curMode = null;
            }
        } else if (m !== null && curMode !== null && m !== curMode && cur.length) {
            chunks.push(cur);
            cur = [];
        }
        cur.push(r);
        if (m !== null) curMode = m;
    }
    if (cur.length) chunks.push(cur);
    return chunks;
}

function mergeRuns(runs: LocationRun[]): LocationRun {
    const segments = runs.flatMap((r) => r.segments);
    return {
        name: journeyName(segments),
        startMs: runs[0].startMs,
        endMs: runs[runs.length - 1].endMs,
        totalSeconds: runs.reduce((s, r) => s + r.totalSeconds, 0),
        segments,
        isMove: true,
        mode: modal(segments.map((s) => s.mode).filter(Boolean) as string[]),
        labelKind: null,
        tz: runs[0].tz,
    };
}

// A maximal run of consecutive transit/short-stop runs (within the break window)
// that contains at least one move is merged into one journey; the transit-bounded
// core (moves + interior waypoint stops) collapses, while short stops before the
// first / after the last move stay separate as their own brief places.
function mergeTransitWaypoints(runs: LocationRun[]): LocationRun[] {
    const out: LocationRun[] = [];
    let i = 0;
    const n = runs.length;
    while (i < n) {
        if (runKind(runs[i]) === 'real_stop') {
            out.push(runs[i]);
            i += 1;
            continue;
        }
        const group = [runs[i]];
        let j = i + 1;
        while (
            j < n &&
            runKind(runs[j]) !== 'real_stop' &&
            runs[j].startMs - runs[j - 1].endMs < BREAK_THRESHOLD_MS
        ) {
            group.push(runs[j]);
            j += 1;
        }
        const transitIdx = group
            .map((r, k) => (runKind(r) === 'transit' ? k : -1))
            .filter((k) => k >= 0);
        if (transitIdx.length) {
            const first = transitIdx[0];
            const last = transitIdx[transitIdx.length - 1];
            group.slice(0, first).forEach((r) => out.push(r));
            // Split the transit-bounded core into one leg per contiguous transport
            // mode, so "walk → bus → walk" reads as three legs, not one blob.
            for (const chunk of splitByMode(group.slice(first, last + 1))) {
                out.push(mergeRuns(chunk));
            }
            group.slice(last + 1).forEach((r) => out.push(r));
            i = j;
        } else {
            out.push(runs[i]);
            i += 1;
        }
    }
    return out;
}

const MOVE_BG = '#9575cd20';

const segColor = (seg: NavSegment) =>
    THEME_COLORS[seg.activityGroup] || CATEGORIES[seg.activity] || '#e0e0e0';

export default function DayNavBar({ navSegments, selectedSegmentId, viewingSegmentId = null, onSelectSegment, hasRecent = false, device, date, onLocationCorrected }: DayNavBarProps) {
    const [activeRunIdx, setActiveRunIdx] = useState<number | null>(null);
    const [editRun, setEditRun] = useState<{ segmentIds: number[]; name?: string | null } | null>(null);

    // Scroll-fade hints: show a soft gradient on whichever edge has more bar
    // off-screen, so a busy (horizontally scrolling) day reads as scrollable.
    const scrollRef = useRef<HTMLDivElement | null>(null);
    const [fade, setFade] = useState({ left: false, right: false });
    const updateFade = useCallback(() => {
        const el = scrollRef.current;
        if (!el) return;
        const { scrollLeft, scrollWidth, clientWidth } = el;
        setFade({
            left: scrollLeft > 1,
            right: scrollLeft + clientWidth < scrollWidth - 1,
        });
    }, []);
    useEffect(() => {
        updateFade();
        const el = scrollRef.current;
        if (!el) return;
        const ro = new ResizeObserver(updateFade);
        ro.observe(el);
        window.addEventListener('resize', updateFade);
        return () => {
            ro.disconnect();
            window.removeEventListener('resize', updateFade);
        };
    }, [updateFade, navSegments]);

    const segments: NavSegment[] = navSegments ?? [];
    if (!segments.length) return null;

    const totalStart = uMs(segments[0].startTime);
    const totalEnd = uMs(segments[segments.length - 1].endTime);
    const totalSpan = totalEnd - totalStart || 1;

    const widthPct = (startMs: number, endMs: number) =>
        ((endMs - startMs) / totalSpan) * 100;

    const locationRuns = buildLocationRuns(segments);

    // On busy days the runs would shrink to unreadable slivers (or clip). Give
    // each run a readable minimum and let the whole bar scroll horizontally when
    // the minimums don't fit. On light days the content is narrower than the
    // viewport, so flexGrow still lays runs out time-proportionally.
    const RUN_MIN_PX = 64; // stops only — keep a place label readable
    const MOVE_MIN_PX = 16; // moves stay thin (just a mode icon), width ∝ duration
    const ACT_MIN_PX = 4; // thin floor so an activity cell never fully vanishes
    const BREAK_PX = 50; // 46 width + 2px margins each side
    const RECENT_PX = 74; // 70 width + 4px left margin
    // A stop is at least RUN_MIN_PX, but grows to fit its activity cells so none
    // collapse to a sliver; the bar scrolls if that overflows the viewport.
    const runMinPx = (run: LocationRun) =>
        run.isMove ? MOVE_MIN_PX : Math.max(RUN_MIN_PX, run.segments.length * ACT_MIN_PX);
    let minContentPx = 0;
    locationRuns.forEach((run, ri) => {
        minContentPx += runMinPx(run);
        const gap = ri > 0 ? run.startMs - locationRuns[ri - 1].endMs : 0;
        if (ri > 0 && gap >= BREAK_THRESHOLD_MS) minContentPx += BREAK_PX;
    });
    if (hasRecent) minContentPx += RECENT_PX;

    // flexGrow for a run = its share of the day (duration %), EXCEPT a GPS-only
    // stay (no photos) is capped small so a long imageless stretch — e.g. a 6 h
    // overnight at home — sits near its min width instead of hogging the bar.
    const GPS_ONLY_GROW = 3;
    const runGrow = (run: LocationRun) => {
        const raw = run.segments.reduce(
            (sum, seg) => sum + widthPct(uMs(seg.startTime), uMs(seg.endTime)), 0);
        const gpsOnly = run.segments.every((s) => s.segmentId == null);
        return gpsOnly ? Math.min(raw, GPS_ONLY_GROW) : raw;
    };

    return (
        <Box sx={{ position: 'relative', width: '100%', mb: 1 }}>
          <Box
            ref={scrollRef}
            onScroll={updateFade}
            sx={{ width: '100%', overflowX: 'auto', overflowY: 'hidden' }}
          >
          <Box sx={{ width: '100%', minWidth: `${minContentPx}px` }}>
            <Box sx={{ display: 'flex', width: '100%' }}>
                {locationRuns.map((run, ri) => {
                    const w = runGrow(run);
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
                                minWidth: runMinPx(run),
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
                                        position: 'relative',
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
                                        '&:hover .daynav-edit-loc': { opacity: 1 },
                                    }}
                                >
                                    <Typography variant="caption" fontWeight={700} noWrap sx={{ lineHeight: 1.2, color: '#fff' }}>
                                        {header.headerText}
                                    </Typography>
                                    <Typography variant="caption" noWrap sx={{ fontSize: '0.65rem', lineHeight: 1.2, color: 'rgba(255,255,255,0.8)' }}>
                                        {fmtDuration(run.totalSeconds)}
                                    </Typography>
                                    {/* Manual reverse-geocode correction — stop runs with real photos only */}
                                    {!run.isMove && device && date && run.segments.some((s) => s.segmentId != null) && (
                                        <Tooltip title="Correct location">
                                            <IconButton
                                                className="daynav-edit-loc"
                                                size="small"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    const ids = run.segments
                                                        .map((s) => s.segmentId)
                                                        .filter((id): id is number => id != null);
                                                    if (ids.length) setEditRun({ segmentIds: ids, name: run.name });
                                                }}
                                                sx={{
                                                    position: 'absolute',
                                                    top: 1,
                                                    right: 1,
                                                    p: '1px',
                                                    color: '#fff',
                                                    opacity: 0,
                                                    transition: 'opacity 0.12s',
                                                    bgcolor: 'rgba(0,0,0,0.25)',
                                                    '&:hover': { bgcolor: 'rgba(0,0,0,0.45)' },
                                                }}
                                            >
                                                <EditLocationAltIcon sx={{ fontSize: 14 }} />
                                            </IconButton>
                                        </Tooltip>
                                    )}
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
                                    // A recording break inside a same-location run: show it here
                                    // in the activity row only (the header above stays continuous).
                                    const prevSeg = si > 0 ? run.segments[si - 1] : null;
                                    const gapBefore = prevSeg ? uMs(seg.startTime) - uMs(prevSeg.endTime) : 0;
                                    const showGap = gapBefore >= BREAK_THRESHOLD_MS;
                                    // GPS-only stay: visited (from the GPS track) but no photos taken.
                                    const isGpsOnly = seg.segmentId == null;
                                    const cellTitle = isGpsOnly ? `No photos · ${range}` : title;
                                    return (
                                      <Fragment key={seg.segmentId ?? si}>
                                        {showGap && prevSeg && (
                                            <Tooltip
                                                title={`No recording · ${hm(uMs(prevSeg.endTime), run.tz)}–${hm(uMs(seg.startTime), run.tz)} · ${fmtDuration(gapBefore / 1000)}`}
                                                followCursor
                                            >
                                                <Box
                                                    sx={{
                                                        flex: '0 0 auto',
                                                        width: 54,
                                                        height: '100%',
                                                        display: 'flex',
                                                        alignItems: 'center',
                                                        justifyContent: 'center',
                                                        mx: '2px',
                                                        background: (theme) =>
                                                            `repeating-linear-gradient(45deg, transparent, transparent 4px, ${theme.palette.action.hover} 4px, ${theme.palette.action.hover} 8px)`,
                                                        borderLeft: '1px dashed',
                                                        borderRight: '1px dashed',
                                                        borderColor: 'text.disabled',
                                                        borderRadius: '4px',
                                                    }}
                                                >
                                                    <Typography
                                                        variant="caption"
                                                        color="text.secondary"
                                                        sx={{ fontSize: 9, lineHeight: 1, fontWeight: 600, whiteSpace: 'nowrap' }}
                                                    >
                                                        ┈ {fmtDuration(gapBefore / 1000)} ┈
                                                    </Typography>
                                                </Box>
                                            </Tooltip>
                                        )}
                                        <Tooltip title={cellTitle} followCursor>
                                            <Box
                                                onClick={() => {
                                                    if (seg.segmentId != null) onSelectSegment(seg.segmentId);
                                                }}
                                                sx={{
                                                    flexBasis: `${segRelW}%`,
                                                    flexGrow: isLastSeg ? 1 : 0,
                                                    flexShrink: 0,
                                                    minWidth: ACT_MIN_PX,
                                                    height: '100%',
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    justifyContent: 'center',
                                                    background: isGpsOnly
                                                        ? (theme) =>
                                                              `repeating-linear-gradient(45deg, ${theme.palette.action.disabledBackground}, ${theme.palette.action.disabledBackground} 5px, transparent 5px, transparent 10px)`
                                                        : background,
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
                                            >
                                                {isGpsOnly && (
                                                    <Typography
                                                        variant="caption"
                                                        color="text.disabled"
                                                        noWrap
                                                        sx={{ fontSize: 9, fontStyle: 'italic', px: '2px' }}
                                                    >
                                                        no photos
                                                    </Typography>
                                                )}
                                            </Box>
                                        </Tooltip>
                                      </Fragment>
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
                    const w = runGrow(run);
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
                                    minWidth: runMinPx(run),
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
          </Box>

            {/* Scroll-fade hints — soft gradient on an edge that has more off-screen */}
            <Box
                sx={{
                    position: 'absolute',
                    left: 0,
                    top: 0,
                    bottom: 0,
                    width: 28,
                    pointerEvents: 'none',
                    opacity: fade.left ? 1 : 0,
                    transition: 'opacity 0.15s',
                    background: (theme) =>
                        `linear-gradient(to right, ${theme.palette.background.default}, transparent)`,
                }}
            />
            <Box
                sx={{
                    position: 'absolute',
                    right: 0,
                    top: 0,
                    bottom: 0,
                    width: 28,
                    pointerEvents: 'none',
                    opacity: fade.right ? 1 : 0,
                    transition: 'opacity 0.15s',
                    background: (theme) =>
                        `linear-gradient(to left, ${theme.palette.background.default}, transparent)`,
                }}
            />

            {device && date && editRun && (
                <StopCorrectionDialog
                    open
                    device={device}
                    date={date}
                    segmentIds={editRun.segmentIds}
                    currentName={editRun.name}
                    onClose={() => setEditRun(null)}
                    onCorrected={onLocationCorrected}
                />
            )}
        </Box>
    );
}

import {
    ChevronLeftRounded,
    ChevronRightRounded,
    RefreshRounded,
} from '@mui/icons-material';
import {
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    Grid,
    IconButton,
    LinearProgress,
    Stack,
    styled,
    Tab,
    Tabs,
    Tooltip,
    Typography,
} from '@mui/material';
import { DaySummary, LocationVisit, MealFood, SummarySegment } from '@utils/types';
import { CATEGORIES, THEME_COLORS } from 'constants/activityColors';
import React, { useState } from 'react';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';
import { CategoryPieChart } from 'components/charts/CategoryChart';
import ReactMarkdown from 'react-markdown';
import ImageWithDate from 'components/common/ImageWithDate';
import ModalWithCloseButton from 'components/common/ModalWithCloseButton';
import { minutesToHM } from './shared';

dayjs.extend(utc);
dayjs.extend(timezone);

// Segment/visit times are naive UTC. Parse as UTC for correct epoch math, and
// display in the capture zone (the segment's own timezone) so times read as
// local wall-clock rather than UTC. Falls back to UTC when the zone is absent.
const uMs = (t: string) => dayjs.utc(t).valueOf();
const hm = (ms: number, tz?: string | null) =>
    (tz ? dayjs(ms).tz(tz) : dayjs.utc(ms)).format('HH:mm');

/**
 * Renders Binary metrics (like Social/Alone) as progress bars
 */
export function BinaryMetricsCard({
    metrics,
    totalImages,
}: {
    metrics: Record<string, number>;
    totalImages: number;
}) {
    return (
        <Card variant="outlined">
            <CardContent>
                <Typography
                    variant="subtitle2"
                    color="text.secondary"
                    gutterBottom
                >
                    State Distribution
                </Typography>
                <Stack spacing={2} mt={1}>
                    {Object.entries(metrics).map(([name, mins]) => (
                        <Box key={name}>
                            <Stack
                                direction="row"
                                justifyContent="space-between"
                            >
                                <Typography variant="body2">{name}</Typography>
                                <Typography variant="body2">
                                    {((mins / totalImages) * 100).toFixed(0)}%
                                </Typography>
                            </Stack>
                            <LinearProgress
                                variant="determinate"
                                value={(mins / totalImages) * 100}
                                sx={{ mt: 0.5 }}
                            />
                        </Box>
                    ))}
                </Stack>
            </CardContent>
        </Card>
    );
}

/**
 * Renders Burst metrics (like Drinking Water) as counts
 */
export function BurstMetricsCard({ bursts }: { bursts: Record<string, number[]> }) {
    if (Object.keys(bursts).length === 0) return null;
    return (
        <Card variant="outlined">
            <CardContent>
                <Typography
                    variant="subtitle2"
                    color="text.secondary"
                    gutterBottom
                >
                    Daily Bursts
                </Typography>
                <Grid container spacing={1} mt={1}>
                    {Object.entries(bursts).map(([name, timestamps]) => (
                        <Grid size={6} key={name}>
                            <Box
                                sx={{
                                    p: 1,
                                    bgcolor: 'action.hover',
                                    borderRadius: 1,
                                    textAlign: 'center',
                                }}
                            >
                                <Typography variant="h6">
                                    {timestamps.length}
                                </Typography>
                                <Typography
                                    variant="caption"
                                    color="text.secondary"
                                >
                                    {name}
                                </Typography>
                            </Box>
                        </Grid>
                    ))}
                </Grid>
            </CardContent>
        </Card>
    );
}

const PeriodTimeTab = styled(Tab)({
    backgroundColor: '#fdf1e3',
    borderRadius: '8px px 0 0',
    marginRight: '4px',
    fontSize: '12px',
    minHeight: '32px',
    padding: '4px 12px',
});

/**
 * Generic Card for any "Period" activity (Eating, Working, etc.) that shows one
 * segment and one summary line at a time.
 */
export function PeriodCard({
    title,
    segments,
    summary,
}: {
    title: string;
    segments: SummarySegment[];
    summary?: string;
}) {
    // State for navigating segments (images/times)
    const [segmentIndex, setSegmentIndex] = useState(0);

    if (!segments || segments.length === 0)
        return (
            <>
                <CardContent>
                    <Typography>No {title} periods detected.</Typography>
                </CardContent>
            </>
        );

    // Split summary by new lines and filter out empty strings
    const summaryLines = summary
        ? summary.split('\n').filter((line) => line.trim() !== '')
        : [];

    const handleNextSegment = () => {
        setSegmentIndex((prev) => (prev + 1) % segments.length);
    };

    const handlePrevSegment = () => {
        setSegmentIndex(
            (prev) => (prev - 1 + segments.length) % segments.length
        );
    };

    const currentSegment = segments[segmentIndex];
    const totalMins =
        segments?.reduce((acc, s) => acc + s.duration / 60, 0) || 0;

    const periodMinutesToHM = (m: number): string => {
        const total = Math.round(m);
        const h = Math.floor(total / 60);
        const mm = total % 60;
        return h === 0 ? `${mm} min` : `${h} h ${mm} min`;
    };

    if (!currentSegment)
        return (
            <>
                <CardContent>
                    <Typography>No data for this period.</Typography>
                </CardContent>
            </>
        );

    return (
        <>
            <CardContent>
                <Stack
                    direction="row"
                    justifyContent="space-between"
                    alignItems="center"
                >
                    <Typography variant="subtitle2" color="text.secondary">
                        {title} ({segments.length} times)
                    </Typography>
                    <Typography variant="caption" fontWeight="bold">
                        Total: {periodMinutesToHM(totalMins)}
                    </Typography>
                </Stack>
                <Box
                    sx={{
                        borderBottom: 1,
                        borderColor: 'divider',
                        marginBottom: 2,
                    }}
                >
                    <Tabs
                        value={segmentIndex}
                        onChange={(_, value) => setSegmentIndex(value)}
                        sx={{ minHeight: '32px', mt: 2 }}
                    >
                        {segments.map((segment, index) => (
                            <PeriodTimeTab
                                key={index}
                                label={`${hm(uMs(segment.startTime), segment.timezone)} - ${hm(uMs(segment.endTime), segment.timezone)}`}
                            />
                        ))}
                    </Tabs>
                </Box>

                {/* 1. Interactive Summary Section */}
                {summaryLines.length > 0 && (
                    <Box
                        sx={{
                            my: 2,
                            p: 1.5,
                            bgcolor: 'action.hover',
                            borderRadius: 1,
                        }}
                    >
                        <Stack direction="row" alignItems="center" spacing={1}>
                            <Typography
                                variant="body2"
                                sx={{
                                    flexGrow: 1,
                                    textAlign: 'center',
                                    fontStyle: 'italic',
                                }}
                            >
                                {summaryLines[segmentIndex]}
                            </Typography>
                        </Stack>
                    </Box>
                )}

                {/* Food detail for this segment (eating focus) */}
                {currentSegment.food && (currentSegment.food.items?.length ?? 0) > 0 && (
                    <Box sx={{ my: 1.5, pl: 1.5, borderLeft: `3px solid ${FOOD_COLOR}` }}>
                        <Stack direction="row" spacing={1} alignItems="baseline" flexWrap="wrap">
                            {currentSegment.food.mealType && (
                                <Typography variant="body2" fontWeight="bold">
                                    {MEAL_ICON[currentSegment.food.mealType] ?? '🍴'}{' '}
                                    {currentSegment.food.mealType[0].toUpperCase() + currentSegment.food.mealType.slice(1)}
                                </Typography>
                            )}
                            {currentSegment.food.totalCalories != null && (
                                <Typography variant="caption" color="warning.main">
                                    ~{currentSegment.food.totalCalories} kcal
                                </Typography>
                            )}
                        </Stack>
                        <Stack component="ul" sx={{ m: 0, mt: 0.25, pl: 2.5 }} spacing={0.1}>
                            {currentSegment.food.items.map((it, i) => (
                                <Typography key={i} component="li" variant="body2">
                                    {fmtItem(it.name, it.portion, it.calories)}
                                </Typography>
                            ))}
                        </Stack>
                        {currentSegment.food.healthiness && (
                            <Typography variant="caption" color="text.secondary" fontStyle="italic">
                                {currentSegment.food.healthiness}
                            </Typography>
                        )}
                    </Box>
                )}

                {/* 2. Interactive Segment Section */}
                <Stack
                    direction="row"
                    alignItems="center"
                    spacing={2}
                    justifyContent="space-between"
                    mt={2}
                    sx={{ width: '100%', flex: '1 1 auto' }}
                >
                    <IconButton
                        onClick={handlePrevSegment}
                        disabled={segments.length <= 1}
                    >
                        <ChevronLeftRounded />
                    </IconButton>

                    <Stack
                        direction="row"
                        spacing={1}
                        mt={1}
                        sx={{
                            overflowX: 'auto',
                            width: '100%',
                            height: '220px',
                        }}
                        justifyContent="center"
                    >
                        {currentSegment.representativeImages?.map(
                            (img, idx) => (
                                <ImageWithDate
                                    key={idx}
                                    image={img}
                                    height="200px"
                                    timeOnly
                                    disableDelete
                                />
                            )
                        )}
                    </Stack>

                    <IconButton
                        onClick={handleNextSegment}
                        disabled={segments.length <= 1}
                    >
                        <ChevronRightRounded />
                    </IconButton>
                </Stack>
            </CardContent>
        </>
    );
}

export function SummaryText({
    summaryText,
    heading = 'Day Overview',
}: {
    summaryText: string;
    heading?: string;
}) {
    return (
        <Card variant="outlined" sx={{ height: '100%' }}>
            <CardContent>
                <Typography
                    variant="subtitle2"
                    color="text.secondary"
                    gutterBottom
                >
                    {heading}
                </Typography>
                <Box
                    sx={{
                        '& p': { m: 0, mb: 1, fontSize: '0.875rem' },
                        '& ul': { m: 0, mb: 1, pl: 2.5 },
                        '& li': { fontSize: '0.875rem' },
                        '& strong': { fontWeight: 600 },
                        '& > :last-child': { mb: 0 },
                    }}
                >
                    {summaryText ? (
                        <ReactMarkdown>{summaryText}</ReactMarkdown>
                    ) : (
                        <Typography variant="body2" fontStyle="italic">
                            No summary available for this day.
                        </Typography>
                    )}
                </Box>
            </CardContent>
        </Card>
    );
}

/**
 * Place-by-place narrative: one description per location visit (a run of
 * consecutive segments at the same place). Coarser than the raw timeline.
 */
export function LocationVisitsCard({ visits }: { visits?: LocationVisit[] }) {
    const described = (visits ?? []).filter((v) => (v.description || '').trim());
    if (described.length === 0) return null;
    return (
        <Card variant="outlined" sx={{ height: '100%' }}>
            <CardContent>
                <Typography
                    variant="subtitle2"
                    color="text.secondary"
                    gutterBottom
                >
                    Places Visited
                </Typography>
                <Stack spacing={1.5} mt={1}>
                    {described.map((v) => (
                        <Box
                            key={v.visitIndex}
                            sx={{
                                pl: 1.5,
                                borderLeft: '3px solid',
                                borderColor: 'divider',
                            }}
                        >
                            <Stack
                                direction="row"
                                spacing={1}
                                alignItems="baseline"
                                flexWrap="wrap"
                            >
                                <Typography variant="body2" fontWeight="bold">
                                    {v.locationName || 'Unknown place'}
                                </Typography>
                                <Typography
                                    variant="caption"
                                    color="text.secondary"
                                >
                                    {hm(uMs(v.startTime), v.timezone)} –{' '}
                                    {hm(uMs(v.endTime), v.timezone)}
                                </Typography>
                            </Stack>
                            <Typography variant="body2" sx={{ mt: 0.25 }}>
                                {v.description}
                            </Typography>
                            {v.eventContext && (
                                <Typography
                                    variant="caption"
                                    color="primary"
                                    sx={{ display: 'block', mt: 0.25 }}
                                >
                                    📍 {v.eventContext}
                                </Typography>
                            )}
                        </Box>
                    ))}
                </Stack>
            </CardContent>
        </Card>
    );
}

const MEAL_ICON: Record<string, string> = {
    breakfast: '🥐',
    lunch: '🥗',
    dinner: '🍽️',
    snack: '🍎',
};

const FOOD_COLOR = THEME_COLORS['Food & Drink'] || '#FF5555';

function fmtItem(name: string, portion?: string, calories?: number | null): string {
    let s = name;
    if (portion) s += ` (${portion})`;
    if (calories != null) s += ` · ~${calories} kcal`;
    return s;
}

// Eating focus: the day's meals with items, rough portions + calories, plus a
// rollup strip. Driven by segment.food (per-meal) + daySummary.food (rollup).
export function MealsCard({ day }: { day: DaySummary }) {
    const meals = (day.segments ?? [])
        .filter((s) => s.food && (s.food.items?.length ?? 0) > 0)
        .sort((a, b) => uMs(a.startTime) - uMs(b.startTime));
    if (meals.length === 0) return null;
    const roll = day.food;

    return (
        <Card variant="outlined" sx={{ borderLeft: `3px solid ${FOOD_COLOR}` }}>
            <CardContent>
                <Stack direction="row" alignItems="center" justifyContent="space-between" flexWrap="wrap" gap={1}>
                    <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                        🍽️ Meals
                    </Typography>
                    {roll && (
                        <Stack direction="row" spacing={0.5} flexWrap="wrap">
                            <Chip size="small" label={`${roll.mealCount} meal${roll.mealCount === 1 ? '' : 's'}`} />
                            {roll.totalCalories != null && (
                                <Chip size="small" color="warning" variant="outlined"
                                    label={`~${roll.totalCalories} kcal`} />
                            )}
                        </Stack>
                    )}
                </Stack>

                <Stack spacing={1.5} mt={1}>
                    {meals.map((seg) => {
                        const f = seg.food as MealFood;
                        return (
                            <Box key={seg.segmentId ?? seg.startTime}
                                sx={{ pl: 1.5, borderLeft: '3px solid', borderColor: 'divider' }}>
                                <Stack direction="row" spacing={1} alignItems="baseline" flexWrap="wrap">
                                    {f.mealType && (
                                        <Typography variant="body2" fontWeight="bold">
                                            {MEAL_ICON[f.mealType] ?? '🍴'} {f.mealType[0].toUpperCase() + f.mealType.slice(1)}
                                        </Typography>
                                    )}
                                    <Typography variant="caption" color="text.secondary">
                                        {hm(uMs(seg.startTime), seg.timezone)}
                                        {seg.locationName ? ` · ${seg.locationName}` : ''}
                                    </Typography>
                                    {f.totalCalories != null && (
                                        <Typography variant="caption" color="warning.main">
                                            ~{f.totalCalories} kcal
                                        </Typography>
                                    )}
                                </Stack>
                                <Stack component="ul" sx={{ m: 0, mt: 0.25, pl: 2.5 }} spacing={0.1}>
                                    {f.items.map((it, i) => (
                                        <Typography key={i} component="li" variant="body2">
                                            {fmtItem(it.name, it.portion, it.calories)}
                                        </Typography>
                                    ))}
                                </Stack>
                                {f.healthiness && (
                                    <Typography variant="caption" color="text.secondary"
                                        sx={{ display: 'block', mt: 0.25, fontStyle: 'italic' }}>
                                        {f.healthiness}
                                    </Typography>
                                )}
                            </Box>
                        );
                    })}
                </Stack>
                <Typography variant="caption" color="text.disabled" sx={{ display: 'block', mt: 1 }}>
                    Portions &amp; calories are rough estimates.
                </Typography>
            </CardContent>
        </Card>
    );
}

export const OverviewSummary = ({
    totalMinutes,
    totalImages,
    startTime,
    endTime,
    timezone,
}: {
    totalMinutes: number;
    totalImages: number;
    startTime?: string;
    endTime?: string;
    timezone?: string | null;
}) => {
    return (
        <Card variant="outlined">
            <CardContent>
                <Typography
                    variant="subtitle2"
                    color="text.secondary"
                    gutterBottom
                >
                    Overview
                </Typography>

                <Typography variant="h6">
                    {minutesToHM(totalMinutes)}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                    Total captured time
                </Typography>

                {startTime && endTime && (
                    <Box mt={1}>
                        <Typography variant="body2" color="text.secondary">
                            {hm(uMs(startTime), timezone)} – {hm(uMs(endTime), timezone)}
                        </Typography>
                    </Box>
                )}

                <Box mt={1}>
                    <Typography variant="body2">
                        Images: <strong>{totalImages}</strong>
                    </Typography>
                </Box>
            </CardContent>
        </Card>
    );
};

// Gaps between segments longer than this are treated as recording breaks:
// collapsed to a fixed-width labeled marker instead of proportional blank space,
// so a long break doesn't squish the actual activity.
const BREAK_THRESHOLD_MS = 15 * 60 * 1000;

// Fixed pixel width of a collapsed break marker; the bar row and the tick row
// both reserve this so their columns stay aligned.
const BREAK_MARKER_W = 56;

type Stretch = {
    segments: SummarySegment[];
    startMs: number;
    endMs: number;
    weight: number; // flex weight = sum of segment weights, keeps columns aligned
    tz: string | null;
};
type TimelineItem =
    | { type: 'stretch'; stretch: Stretch; key: string }
    | { type: 'break'; gapMs: number; startTime: string; endTime: string; tz: string | null; key: string };

const segWeight = (s: SummarySegment) => Math.max(s.duration, 1);

// Clock-aligned 3-hour ticks (…, 09:00, 12:00, 15:00, …) inside one continuous
// stretch. Time is linear within a stretch (breaks only fall between stretches),
// so ticks position correctly by percentage.
const TICK_STEP_H = 3;
function stretchTicks(startMs: number, endMs: number, tz?: string | null): { pct: number; label: string }[] {
    const spanMs = endMs - startMs;
    if (spanMs <= 0) return [];
    const ticks: { pct: number; label: string }[] = [];
    let t = (tz ? dayjs(startMs).tz(tz) : dayjs.utc(startMs)).startOf('hour');
    while (t.valueOf() <= startMs || t.hour() % TICK_STEP_H !== 0) t = t.add(1, 'hour');
    while (t.valueOf() < endMs) {
        const pct = ((t.valueOf() - startMs) / spanMs) * 100;
        if (pct > 2 && pct < 98) ticks.push({ pct, label: t.format('HH:mm') });
        t = t.add(TICK_STEP_H, 'hour');
    }
    return ticks;
}

export function Timeline({ daySummary }: { daySummary: DaySummary }) {
    const segments = daySummary?.segments ?? [];

    // Split segments into continuous stretches at every recording break. Each
    // stretch renders as a linear time axis; breaks between them collapse to a
    // fixed labeled marker so a long gap doesn't squish the activity.
    const items = React.useMemo<TimelineItem[]>(() => {
        const result: TimelineItem[] = [];
        let current: Stretch | null = null;
        segments.forEach((segment, index) => {
            const segStart = uMs(segment.startTime);
            const segEnd = uMs(segment.endTime);
            if (index > 0) {
                const prevEnd = uMs(segments[index - 1].endTime);
                const gapMs = segStart - prevEnd;
                if (gapMs >= BREAK_THRESHOLD_MS) {
                    result.push({
                        type: 'break',
                        gapMs,
                        startTime: segments[index - 1].endTime,
                        endTime: segment.startTime,
                        tz: segment.timezone ?? null,
                        key: `break-${index}`,
                    });
                    current = null;
                }
            }
            if (!current) {
                current = { segments: [], startMs: segStart, endMs: segEnd, weight: 0, tz: segment.timezone ?? null };
                result.push({ type: 'stretch', stretch: current, key: `stretch-${index}` });
            }
            current.segments.push(segment);
            current.endMs = segEnd;
            current.weight += segWeight(segment);
        });
        return result;
    }, [segments]);

    return (
        <Card variant="outlined" sx={{ height: '100%' }}>
            <CardContent>
                <Typography
                    variant="subtitle2"
                    color="text.secondary"
                    gutterBottom
                >
                    Timeline
                </Typography>
                {segments.length > 0 && (
                    <Box sx={{ position: 'relative', width: '100%', pt: 1 }}>
                        {/* Segment bars, grouped into stretches with breaks collapsed */}
                        <Box sx={{ display: 'flex', flexDirection: 'row', alignItems: 'stretch', width: '100%' }}>
                            {items.map((item) => {
                                if (item.type === 'break') {
                                    return (
                                        <Tooltip
                                            key={item.key}
                                            title={`No recording: ${hm(uMs(item.startTime), item.tz)} – ${hm(uMs(item.endTime), item.tz)} (${minutesToHM(item.gapMs / 60000)})`}
                                            followCursor
                                        >
                                            <Box
                                                sx={{
                                                    flex: `0 0 ${BREAK_MARKER_W}px`,
                                                    height: 48,
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    justifyContent: 'center',
                                                    borderLeft: '1px dashed',
                                                    borderRight: '1px dashed',
                                                    borderColor: 'divider',
                                                    backgroundColor: 'transparent',
                                                }}
                                            >
                                                <Typography
                                                    variant="caption"
                                                    color="text.disabled"
                                                    sx={{ fontSize: 10, whiteSpace: 'nowrap' }}
                                                >
                                                    ┈ {minutesToHM(item.gapMs / 60000)} ┈
                                                </Typography>
                                            </Box>
                                        </Tooltip>
                                    );
                                }
                                return (
                                    <Box
                                        key={item.key}
                                        sx={{ flexGrow: item.stretch.weight, flexBasis: 0, display: 'flex', minWidth: 0 }}
                                    >
                                        {item.stretch.segments.map((segment, si) => (
                                            <Tooltip
                                                key={si}
                                                title={`${segment.activity}: ${hm(uMs(segment.startTime), segment.timezone)} – ${hm(uMs(segment.endTime), segment.timezone)} (${minutesToHM(segment.duration / 60)})`}
                                                followCursor
                                            >
                                                <Box
                                                    sx={{
                                                        height: 48,
                                                        flexGrow: segWeight(segment),
                                                        flexBasis: 0,
                                                        minWidth: 2,
                                                        backgroundColor:
                                                            THEME_COLORS[segment.activityGroup] ||
                                                            CATEGORIES[segment.activity] ||
                                                            '#bdc3c7',
                                                    }}
                                                />
                                            </Tooltip>
                                        ))}
                                    </Box>
                                );
                            })}
                        </Box>

                        {/* Time axis — a tick every 3h within each stretch, plus the
                            resume time at the start of a stretch that follows a break.
                            The break resets the axis instead of skewing it. */}
                        <Box sx={{ display: 'flex', width: '100%', mt: '2px', alignItems: 'flex-start' }}>
                            {items.map((item, i) => {
                                if (item.type === 'break') {
                                    return <Box key={item.key} sx={{ flex: `0 0 ${BREAK_MARKER_W}px` }} />;
                                }
                                const { startMs, endMs, weight, tz } = item.stretch;
                                const ticks = stretchTicks(startMs, endMs, tz);
                                const afterBreak = i > 0 && items[i - 1].type === 'break';
                                const beforeBreak = i < items.length - 1 && items[i + 1].type === 'break';
                                return (
                                    <Box
                                        key={item.key}
                                        sx={{ flexGrow: weight, flexBasis: 0, minWidth: 0, position: 'relative', height: 16 }}
                                    >
                                        {afterBreak && (
                                            <Typography variant="caption" color="text.secondary"
                                                sx={{ position: 'absolute', left: 0, fontSize: 10, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                                                {hm(startMs, tz)}
                                            </Typography>
                                        )}
                                        {ticks.map((tick) => (
                                            <Typography key={tick.label} variant="caption" color="text.disabled"
                                                sx={{ position: 'absolute', left: `${tick.pct}%`, transform: 'translateX(-50%)', fontSize: 10, fontVariantNumeric: 'tabular-nums' }}>
                                                {tick.label}
                                            </Typography>
                                        ))}
                                        {beforeBreak && (
                                            <Typography variant="caption" color="text.secondary"
                                                sx={{ position: 'absolute', right: 0, fontSize: 10, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                                                {hm(endMs, tz)}
                                            </Typography>
                                        )}
                                    </Box>
                                );
                            })}
                        </Box>
                    </Box>
                )}
            </CardContent>
        </Card>
    );
}

export const ActivitySummary = ({
    categoryEntries,
    categoryMinutes,
    totalMinutes,
}: {
    categoryEntries: [string, number][];
    categoryMinutes: { [key: string]: number };
    totalMinutes: number;
}) => {
    return (
        <Card variant="outlined" sx={{ height: '100%' }}>
            <CardContent>
                <Typography
                    variant="subtitle2"
                    color="text.secondary"
                    gutterBottom
                >
                    Activity categories
                </Typography>

                {categoryEntries.length === 0 && (
                    <Typography variant="body2" color="text.secondary">
                        No category data.
                    </Typography>
                )}

                <Stack mt={4} justifyContent="center" alignItems="center">
                    <CategoryPieChart
                        categoryMinutes={categoryMinutes}
                        totalMinutes={totalMinutes}
                    />
                </Stack>
            </CardContent>
        </Card>
    );
};

export const ReprocessButton = ({
    onReprocess,
    isLoading,
}: {
    onReprocess: (resegment: boolean, reannotate: boolean) => void;
    isLoading: boolean;
}) => {
    const [show, setShow] = useState(false);
    const [resegment, setResegment] = useState(false);
    const [reannotate, setReannotate] = useState(false);

    return (
        <>
            <Button
                startIcon={<RefreshRounded />}
                variant="outlined"
                onClick={() => setShow(true)}
                disabled={isLoading}
                sx={{ backgroundColor: 'background.paper' }}
            >
                {isLoading ? 'Processing...' : 'Reprocess'}
            </Button>
            <ModalWithCloseButton
                open={show}
                onClose={() => setShow(false)}
                fitContent
            >
                <Stack alignItems="center" p={4} spacing={2}>
                    <Typography variant="h6">Reprocess Options</Typography>
                    <Stack direction="row" spacing={2}>
                        <Button
                            variant={resegment ? 'contained' : 'outlined'}
                            onClick={() => setResegment(!resegment)}
                        >
                            Resegment
                        </Button>
                        <Button
                            variant={reannotate ? 'contained' : 'outlined'}
                            onClick={() => setReannotate(!reannotate)}
                        >
                            Reannotate
                        </Button>
                    </Stack>
                    <Button
                        variant="contained"
                        onClick={() => {
                            onReprocess(resegment, reannotate);
                            setShow(false);
                        }}
                        disabled={isLoading}
                    >
                        {isLoading ? 'Processing...' : 'Confirm'}
                    </Button>
                </Stack>
            </ModalWithCloseButton>
        </>
    );
};

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
import { DaySummary, SummarySegment } from '@utils/types';
import { CATEGORIES, THEME_COLORS } from 'constants/activityColors';
import React, { useState } from 'react';
import dayjs from 'dayjs';
import { CategoryPieChart } from 'components/charts/CategoryChart';
import ImageWithDate from 'components/common/ImageWithDate';
import ModalWithCloseButton from 'components/common/ModalWithCloseButton';
import { minutesToHM } from './shared';

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
                                label={`${dayjs(segment.startTime).format('HH:mm')} - ${dayjs(segment.endTime).format('HH:mm')}`}
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

export function SummaryText({ summaryText }: { summaryText: string }) {
    return (
        <Card variant="outlined" sx={{ height: '100%' }}>
            <CardContent>
                <Typography
                    variant="subtitle2"
                    color="text.secondary"
                    gutterBottom
                >
                    Day Overview
                </Typography>
                <Typography
                    variant="body2"
                    fontStyle="italic"
                    sx={{ whiteSpace: 'pre-line' }}
                >
                    {summaryText || 'No summary available for this day.'}
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
}: {
    totalMinutes: number;
    totalImages: number;
    startTime?: string;
    endTime?: string;
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
                            {dayjs(startTime).format('HH:mm')} – {dayjs(endTime).format('HH:mm')}
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

export function Timeline({ daySummary }: { daySummary: DaySummary }) {
    const segments = daySummary?.segments ?? [];

    const firstStart = segments.length > 0 ? dayjs(segments[0].startTime).valueOf() : null;
    const lastEnd = segments.length > 0 ? dayjs(segments[segments.length - 1].endTime).valueOf() : null;
    const totalSpanMs = firstStart != null && lastEnd != null ? lastEnd - firstStart : 0;

    // Hourly tick marks within the span
    const ticks = React.useMemo(() => {
        if (!firstStart || !totalSpanMs) return [];
        const result: { pct: number; label: string }[] = [];
        // Start at the next whole hour after firstStart
        let t = dayjs(firstStart).startOf('hour').add(1, 'hour').valueOf();
        while (t < lastEnd!) {
            result.push({
                pct: ((t - firstStart) / totalSpanMs) * 100,
                label: dayjs(t).format('HH:mm'),
            });
            t = dayjs(t).add(1, 'hour').valueOf();
        }
        return result;
    }, [firstStart, lastEnd, totalSpanMs]);

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
                {segments.length > 0 && totalSpanMs > 0 && (
                    <Box sx={{ position: 'relative', width: '100%', pt: 1 }}>
                        {/* Segment bars */}
                        <Box sx={{ display: 'flex', flexDirection: 'row', width: '100%' }}>
                            {segments.map((segment: SummarySegment, index: number) => {
                                const segStartMs = dayjs(segment.startTime).valueOf();
                                const segEndMs = dayjs(segment.endTime).valueOf();
                                const prevEndMs = index === 0
                                    ? firstStart!
                                    : dayjs(segments[index - 1].endTime).valueOf();

                                const gapPct = ((segStartMs - prevEndMs) / totalSpanMs) * 100;
                                const widthPct = ((segEndMs - segStartMs) / totalSpanMs) * 100;

                                return (
                                    <React.Fragment key={index}>
                                        {gapPct > 0 && (
                                            <Box sx={{ width: `${gapPct}%`, height: 48, backgroundColor: 'transparent' }} />
                                        )}
                                        <Tooltip
                                            title={`${segment.activity}: ${dayjs(segment.startTime).format('HH:mm')} – ${dayjs(segment.endTime).format('HH:mm')} (${minutesToHM(segment.duration / 60)})`}
                                            followCursor
                                        >
                                            <Box
                                                sx={{
                                                    height: 48,
                                                    width: `${widthPct}%`,
                                                    minWidth: 2,
                                                    backgroundColor:
                                                        THEME_COLORS[segment.activityGroup] ||
                                                        CATEGORIES[segment.activity] ||
                                                        '#bdc3c7',
                                                }}
                                            />
                                        </Tooltip>
                                    </React.Fragment>
                                );
                            })}
                        </Box>

                        {/* X-axis tick marks */}
                        <Box sx={{ position: 'relative', width: '100%', height: 20, mt: '2px' }}>
                            {ticks.map(({ pct, label }) => (
                                <Box
                                    key={label}
                                    sx={{
                                        position: 'absolute',
                                        left: `${pct}%`,
                                        transform: 'translateX(-50%)',
                                        display: 'flex',
                                        flexDirection: 'column',
                                        alignItems: 'center',
                                    }}
                                >
                                    <Box sx={{ width: '1px', height: 4, backgroundColor: 'text.disabled' }} />
                                    <Typography variant="caption" color="text.disabled" sx={{ fontSize: 10, lineHeight: 1 }}>
                                        {label}
                                    </Typography>
                                </Box>
                            ))}
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

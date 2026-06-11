import {
    ChevronLeftRounded,
    ChevronRightRounded,
    RefreshRounded,
    SettingsRounded,
} from '@mui/icons-material';
import {
    alpha,
    Box,
    Button,
    Card,
    CardContent,
    Grid,
    IconButton,
    LinearProgress,
    Skeleton,
    Stack,
    styled,
    Tab,
    Tabs,
    Tooltip,
    Typography,
} from '@mui/material';
import { CustomGoal, DaySummary, SummarySegment } from '@utils/types';
import { updateUserGoals } from 'apis/browsing';
import { getDaySummary, processDate } from 'apis/process';
import { CATEGORIES, THEME_COLORS } from 'constants/activityColors';
import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router';
import useSWR from 'swr';
import 'utils/animation.css';
import { CategoryPieChart } from './CategoryChart';
import GoalConfig from './GoalConfig';
import ImageWithDate from './ImageWithDate';
import ModalWithCloseButton from './ModalWithCloseButton';
import dayjs from 'dayjs';

const minutesToHM = (m: number): string => {
    const total = Math.round(m);
    const h = Math.floor(total / 60);
    const mm = total % 60;
    if (h === 0) return `${mm} min`;
    if (mm === 0) return `${h} h`;
    return `${h} h ${mm} min`;
};

const DaySummaryComponent = () => {
    const [searchParams] = useSearchParams();
    const date = searchParams.get('date');
    const device = searchParams.get('device') || '';
    const [openModal, setOpenModal] = React.useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [periodIndex, setPeriodIndex] = useState(0);

    const {
        data: daySummary,
        isLoading: dayLoading,
        error: isError,
        mutate,
    } = useSWR(
        { key: "day-summary", date, device },
        () => {
            if (!date || !device) return null;
            return getDaySummary(device, date);
        },
        {
            revalidateOnFocus: false,
            revalidateIfStale: false,
            shouldRetryOnError: false,
        }
    );

    const handleProcess = async (
        resegment: boolean = false,
        reannotate: boolean = false
    ) => {
        setIsLoading(true);
        try {
            await processDate(device, date || '', resegment, reannotate);
            mutate();
        } catch (error) {
            console.error('Error processing date:', error);
        }
        setIsLoading(false);
    };

    const handleGoalSave = async (goals: CustomGoal[]) => {
        setOpenModal(false);
        updateUserGoals(goals, device);
        handleProcess();
        mutate();
    };

    useEffect(() => {
        // Reset period index when daySummary changes to avoid out-of-bounds
        setPeriodIndex(0);
    }, [daySummary]);

    if (isLoading || dayLoading)
        return (
            <Skeleton 
                width="100%"
                height={400}
                variant="rounded"
            />
        );

    if (isError || !daySummary || isLoading)
        return (
            <Card
                variant="outlined"
                sx={{ backgroundColor: alpha('#333', 0.2) }}
            >
                <CardContent>
                    <Stack
                        spacing={0}
                        padding={0}
                        alignItems="center"
                        justifyContent="center"
                    >
                        <Typography p={2} color="text.secondary">
                            No Summary Available
                        </Typography>
                        <ReprocessButton
                            onReprocess={handleProcess}
                            isLoading={isLoading}
                        />
                    </Stack>
                </CardContent>
            </Card>
        );

    const allPeriodNames = Object.keys(daySummary.periodMetrics || {});
    const currentChosenPeriodName =
        allPeriodNames[periodIndex] || allPeriodNames[0] || '';

    return (
        <Stack spacing={2} padding={2}>
            {/* Header omitted for brevity, same as your original */}
            <Stack
                direction="row"
                justifyContent="space-between"
                alignItems="flex-end"
                width="100%"
            >
                <Box>
                    {/* Header Section */}
                    <Typography variant="h6" fontWeight="bold">
                        Day Summary
                    </Typography>
                    <Typography variant="subtitle1" color="text.secondary">
                        {date
                            ? new Date(date).toLocaleDateString(undefined, {
                                  dateStyle: 'full',
                              })
                            : 'Overview'}
                    </Typography>
                </Box>
                <Stack direction="row" alignItems="flex-end" spacing={1}>
                    <ReprocessButton
                        onReprocess={handleProcess}
                        isLoading={isLoading}
                    />
                    <Button
                        startIcon={<SettingsRounded />}
                        variant="outlined"
                        onClick={() => setOpenModal(true)}
                    >
                        Configure Goals
                    </Button>
                </Stack>
            </Stack>

            <Grid container spacing={2}>
                {/* 1. Overview & Narrative */}
                <Grid size={4}>
                    <OverviewSummary
                        totalMinutes={daySummary.totalMinutes}
                        totalImages={daySummary.totalImages}
                        startTime={daySummary.segments[0]?.startTime}
                        endTime={daySummary.segments[daySummary.segments.length - 1]?.endTime}
                    />
                </Grid>
                <Grid size={8}>
                    <SummaryText summaryText={daySummary.summaryText} />
                </Grid>

                {/* 2. Binary & Bursts (State & Frequency) */}
                <Grid size={4}>
                    <Stack spacing={2}>
                        <BinaryMetricsCard
                            metrics={daySummary.binaryMetrics}
                            totalImages={daySummary.totalImages}
                        />
                        <BurstMetricsCard bursts={daySummary.burstMetrics} />
                        <ActivitySummary
                            categoryEntries={Object.entries(
                                daySummary.categoryMinutes || {}
                            ).sort((a, b) => b[1] - a[1])}
                            categoryMinutes={daySummary.categoryMinutes}
                            totalMinutes={daySummary.totalMinutes}
                        />
                    </Stack>
                </Grid>

                {/* 3. Periods (Duration Events like Eating, Exercise) */}
                <Grid size={8}>
                    <Stack spacing={2} sx={{ height: '100%' }}>
                        <Box>
                            <Tabs
                                value={periodIndex}
                                onChange={(_, value) => setPeriodIndex(value)}
                                sx={{
                                    transform: 'translateX(-8px)',
                                    minHeight: '32px',
                                    '& .MuiTabs-scroller': {
                                        display: 'flex',
                                        justifyContent: 'flex-end',
                                    },
                                }}
                            >
                                {Object.keys(
                                    daySummary.periodMetrics || {}
                                ).map((name, index) => (
                                    <Tab
                                        key={index}
                                        label={name}
                                        value={index}
                                        sx={{
                                            borderRadius: '8px 8px 0 0',
                                            marginRight: '4px',
                                            fontSize: '12px',
                                            minHeight: '32px',
                                            padding: '4px 12px',
                                            backgroundColor:
                                                CATEGORIES[name] + '30',
                                            color: '#fff',
                                            '&.Mui-selected': {
                                                color: '#fff',
                                                backgroundColor:
                                                    CATEGORIES[name],
                                                borderColor: CATEGORIES[name],
                                            },
                                        }}
                                    />
                                ))}
                            </Tabs>
                            <Card variant="outlined">
                                <PeriodCard
                                    title={currentChosenPeriodName}
                                    segments={
                                        daySummary.periodMetrics[
                                            currentChosenPeriodName
                                        ]
                                    }
                                    summary={
                                        daySummary.customSummaries[
                                            currentChosenPeriodName
                                        ]
                                    }
                                />
                            </Card>
                        </Box>
                        <Timeline daySummary={daySummary} />
                    </Stack>
                </Grid>
            </Grid>
            <ModalWithCloseButton
                open={openModal}
                onClose={() => setOpenModal(false)}
                fitContent
            >
                <GoalConfig onSave={handleGoalSave} />
            </ModalWithCloseButton>
        </Stack>
    );
};

/**
 * Renders Binary metrics (like Social/Alone) as progress bars
 */
function BinaryMetricsCard({
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
function BurstMetricsCard({ bursts }: { bursts: Record<string, number[]> }) {
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

/**
 * Generic Card for any "Period" activity (Eating, Working, etc.)
 */
/**
 * Enhanced PeriodCard that shows one segment and one summary line at a time.
 */

const PeriodTimeTab = styled(Tab)({
    backgroundColor: '#fdf1e3',
    borderRadius: '8px px 0 0',
    marginRight: '4px',
    fontSize: '12px',
    minHeight: '32px',
    padding: '4px 12px',
});

function PeriodCard({
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

    const minutesToHM = (m: number): string => {
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
                        Total: {minutesToHM(totalMins)}
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

export default DaySummaryComponent;

function SummaryText({ summaryText }: { summaryText: string }) {
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

const OverviewSummary = ({
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

function Timeline({ daySummary }: { daySummary: DaySummary }) {
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

const ActivitySummary = ({
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

const ReprocessButton = ({
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

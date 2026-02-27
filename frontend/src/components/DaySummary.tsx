import {
    Box,
    Button,
    Card,
    CardContent,
    CircularProgress,
    Divider,
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
import { CustomGoal, DaySummary, SummarySegment } from '@utils/types';
import { getDaySummary, processDate } from 'apis/process';
import { CATEGORIES } from 'constants/activityColors';
import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router';
import { useAppSelector } from 'reducers/hooks';
import useSWR from 'swr';
import 'utils/animation.css';
import { CategoryPieChart } from './CategoryChart';
import ImageWithDate from './ImageWithDate';
import 'utils/animation.css';
import ModalWithCloseButton from './ModalWithCloseButton';
import GoalConfig from './GoalConfig';
import {
    ChevronLeftRounded,
    ChevronRightRounded,
    HistoryRounded,
    RefreshRounded,
    SettingsRounded,
} from '@mui/icons-material';
import { updateUserGoals } from 'apis/browsing';

const minutesToHM = (m: number): string => {
    const total = Math.round(m);
    const h = Math.floor(total / 60);
    const mm = total % 60;
    if (h === 0) return `${mm} min`;
    if (mm === 0) return `${h} h`;
    return `${h} h ${mm} min`;
};

const safePercent = (num: number, denom: number): number =>
    denom > 0 ? (num / denom) * 100 : 0;

const DaySummaryComponent = () => {
    const [searchParams] = useSearchParams();
    const date = searchParams.get('date');
    const deviceId = useAppSelector((state) => state.auth.deviceId) || '';
    const [openModal, setOpenModal] = React.useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [periodIndex, setPeriodIndex] = useState(0);

    const {
        data: daySummary,
        isLoading: dayLoading,
        error: isError,
        mutate,
    } = useSWR({ date, deviceId }, () => getDaySummary(deviceId, date || ''), {
        revalidateOnFocus: false,
    });

    const handleProcess = async (reprocess: boolean) => {
        setIsLoading(true);
        return processDate(deviceId, date || '', reprocess).then(() => {
            mutate();
            setIsLoading(false);
        });
    };

    const handleGoalSave = async (goals: CustomGoal[]) => {
        setOpenModal(false);
        updateUserGoals(goals, deviceId);
        handleProcess(false);
        mutate();
    };

    useEffect(() => {
        // Reset period index when daySummary changes to avoid out-of-bounds
        setPeriodIndex(0);
    }, [daySummary]);

    if (isLoading || dayLoading)
        return (
            <Stack alignItems="center" p={4}>
                <CircularProgress />
            </Stack>
        );
    if (isError || !daySummary)
        return (
            <>
                <Typography p={2}>No data available.</Typography>
                <Button
                    startIcon={<HistoryRounded />}
                    variant="outlined"
                    onClick={() => handleProcess(true)}
                >
                    Reprocess
                </Button>
            </>
        );

    const allPeriodNames = Object.keys(daySummary.periodMetrics);
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
                    <Button
                        startIcon={<RefreshRounded />}
                        variant="outlined"
                        onClick={() => handleProcess(false)}
                    >
                        Sync Images
                    </Button>
                    <Button
                        startIcon={<HistoryRounded />}
                        variant="outlined"
                        onClick={() => handleProcess(true)}
                    >
                        Reprocess
                    </Button>
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
                                daySummary.categoryMinutes
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
                                {Object.keys(daySummary.periodMetrics).map(
                                    (name, index) => (
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
                                                backgroundColor: CATEGORIES[name] + '30',
                                                color: '#fff',
                                                "&.Mui-selected": {
                                                    color: '#fff',
                                                    backgroundColor: CATEGORIES[name],
                                                    borderColor: CATEGORIES[name],
                                                },
                                            }}
                                        />
                                    )
                                )}
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
                                label={`${segment.startTime.slice(0, 5)} - ${segment.endTime.slice(0, 5)}`}
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
                        sx={{ overflowX: 'auto', width: '100%', height: '220px' }}
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
}: {
    totalMinutes: number;
    totalImages: number;
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

                <Box mt={2}>
                    <Typography variant="body2">
                        Images: <strong>{totalImages}</strong>
                    </Typography>
                </Box>
            </CardContent>
        </Card>
    );
};

function Timeline({ daySummary }: { daySummary: DaySummary }) {
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
                {daySummary && (
                    <Stack
                        direction="row"
                        spacing={0}
                        sx={{
                            overflowX: 'auto',
                            maxWidth: '100%',
                            minWidth: '400px',
                            pt: 1,
                            justifyContent: 'center',
                        }}
                        flexWrap="wrap"
                    >
                        {daySummary.segments.map(
                            (segment: SummarySegment, index: number) => (
                                <Tooltip
                                    title={`${segment.activity}: ${segment.startTime} - ${segment.endTime}`}
                                    key={index}
                                    followCursor
                                >
                                    <Box
                                        sx={{
                                            height: 48,
                                            width: segment.duration / 3600 / 20,
                                            backgroundColor:
                                                CATEGORIES[segment.activity] ||
                                                '#bdc3c7',
                                        }}
                                        key={index}
                                    ></Box>
                                </Tooltip>
                            )
                        )}
                    </Stack>
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

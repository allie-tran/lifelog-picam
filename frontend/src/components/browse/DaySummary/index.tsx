import {
    SettingsRounded,
} from '@mui/icons-material';
import {
    alpha,
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    Grid,
    LinearProgress,
    Skeleton,
    Stack,
    Tab,
    Tabs,
    Tooltip,
    Typography,
} from '@mui/material';
import { CustomGoal } from '@utils/types';
import { updateUserGoals } from 'apis/browsing';
import { getDaySummary, processDate } from 'apis/process';
import { CATEGORIES } from 'constants/activityColors';
import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router';
import useSWR from 'swr';
import 'utils/animation.css';
import GoalConfig from 'components/meta/GoalConfig';
import ModalWithCloseButton from 'components/common/ModalWithCloseButton';
import {
    ActivitySummary,
    BinaryMetricsCard,
    BurstMetricsCard,
    LocationVisitsCard,
    MealsCard,
    OverviewSummary,
    PeriodCard,
    ReprocessButton,
    SummaryText,
    Timeline,
} from './cards';

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
            refreshInterval: (data) => data?.processing ? 3000 : 0,
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

    // Backend is building the summary — no segments yet
    if (daySummary?.processing && !daySummary.segments?.length)
        return (
            <Card variant="outlined" sx={{ backgroundColor: alpha('#333', 0.2) }}>
                <CardContent>
                    <Stack spacing={1} alignItems="center" justifyContent="center" py={4}>
                        <Typography color="text.secondary">Building day summary…</Typography>
                        <LinearProgress sx={{ width: '60%' }} />
                    </Stack>
                </CardContent>
            </Card>
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
                    {daySummary.processing ? (
                        <Tooltip title="This summary is out of date — a refresh is running in the background. It will update automatically.">
                            <Chip
                                size="small"
                                color="warning"
                                variant="outlined"
                                label="Updating…"
                                sx={{ alignSelf: 'center' }}
                            />
                        </Tooltip>
                    ) : daySummary.updated ? (
                        <Tooltip title="New activity was recorded since this summary was written — it will refresh shortly.">
                            <Chip
                                size="small"
                                color="warning"
                                variant="outlined"
                                label="Out of date"
                                sx={{ alignSelf: 'center' }}
                            />
                        </Tooltip>
                    ) : null}
                    {daySummary.processing && (
                        <Tooltip title="Generating summary…">
                            <LinearProgress sx={{ width: 80, alignSelf: 'center' }} />
                        </Tooltip>
                    )}
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
                        timezone={daySummary.segments[0]?.timezone}
                    />
                </Grid>
                <Grid size={8}>
                    <SummaryText summaryText={daySummary.summaryText} />
                </Grid>

                {/* Eating focus: the day's meals with food detail */}
                <Grid size={12}>
                    <MealsCard day={daySummary} />
                </Grid>

                {/* Place-by-place narrative */}
                {(daySummary.locationVisits?.length ?? 0) > 0 && (
                    <Grid size={12}>
                        <LocationVisitsCard visits={daySummary.locationVisits} />
                    </Grid>
                )}

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

export default DaySummaryComponent;

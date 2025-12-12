import {
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    CircularProgress,
    Divider,
    Grid,
    LinearProgress,
    Stack,
    Tooltip,
    Typography,
} from '@mui/material';
import { DaySummary, SummarySegment } from '@utils/types';
import { getDaySummary, processDate } from 'apis/process';
import { useSearchParams } from 'react-router';
import { useAppSelector } from 'reducers/hooks';
import useSWR from 'swr';
import 'utils/animation.css';
import { CategoryPieChart } from './CategoryChart';
import { CATEGORIES } from 'constants/activityColors';
import ImageWithDate from './ImageWithDate';
import React from 'react';

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
    const [searchParams, _] = useSearchParams();
    const date = searchParams.get('date');
    const deviceId = useAppSelector((state) => state.auth.deviceId) || '';

    const {
        data: daySummary,
        isLoading,
        mutate,
    } = useSWR({ date, deviceId }, () => getDaySummary(deviceId, date || ''), {
        revalidateOnFocus: false,
    });

    if (isLoading) {
        return (
            <Stack spacing={2} alignItems="center" padding={2}>
                <Typography variant="body2"> <i>Loading day summary...</i></Typography>
                <CircularProgress />
            </Stack>
        );
    }

    if (!daySummary) {
        return (
            <Button
                variant="contained"
                onClick={() =>
                    processDate(deviceId, date || '').then(() => {
                        alert(
                            'The day is being processed. Please refresh later.'
                        );
                    })
                }
            >
                Process Activities for This Day
            </Button>
        );
    }

    const {
        socialMinutes,
        aloneMinutes,
        categoryMinutes,
        foodDrinkMinutes,
        foodDrinkSegments,
        foodDrinkSummary,
        totalImages,
        totalMinutes,
    } = daySummary;

    const socialPercent = safePercent(
        socialMinutes,
        socialMinutes + aloneMinutes
    );
    const alonePercent = safePercent(
        aloneMinutes,
        socialMinutes + aloneMinutes
    );

    const categoryEntries = Object.entries(categoryMinutes).sort(
        (a, b) => b[1] - a[1]
    );

    return (
        <Stack spacing={2} alignItems="center" padding={2}>
            <Typography variant="h6" fontWeight="bold">
                Day Summary
            </Typography>
            <Typography variant="body1">
                Minutes: {daySummary.totalMinutes.toPrecision(3)} | Images:{' '}
                {daySummary.totalImages}
            </Typography>
            <Grid container spacing={2}>
                {/* Overview */}
                <Grid container size={4}>
                    <Grid size={12}>
                        <OverviewSummary
                            totalMinutes={totalMinutes}
                            totalImages={totalImages}
                            socialPercent={socialPercent}
                            alonePercent={alonePercent}
                        />
                    </Grid>
                    <Grid size={12}>{SocialSummary()}</Grid>
                    <Grid size={12}>
                        <ActivitySummary
                            categoryEntries={categoryEntries}
                            categoryMinutes={categoryMinutes}
                            totalMinutes={totalMinutes}
                        />
                    </Grid>
                </Grid>
                <Grid container size={8}>
                    <Grid size={12}>
                        <FoodDrinkSummary
                            foodDrinkMinutes={foodDrinkMinutes}
                            foodDrinkSummary={foodDrinkSummary}
                            foodDrinkSegments={foodDrinkSegments}
                        />
                    </Grid>
                    <Grid size={12}>
                        {' '}
                        {daySummary && (
                            <SummaryText summaryText={daySummary.summaryText} />
                        )}
                    </Grid>
                    <Grid size={12}>
                        {<Timeline daySummary={daySummary} />}
                    </Grid>
                </Grid>
            </Grid>

            <Button
                variant="contained"
                onClick={() =>
                    processDate(deviceId, date || '').then(() => {
                        alert(
                            'The day is being processed. Please refresh later.'
                        );
                        mutate();
                    })
                }
            >
                Process Unprocessed Images
            </Button>
            <Button
                variant="contained"
                onClick={() =>
                    processDate(deviceId, date || '', true).then(() => {
                        alert(
                            'The day is being processed. Please refresh later.'
                        );
                        mutate();
                    })
                }
            >
                Re-process Entire Day
            </Button>
        </Stack>
    );

    function SocialSummary() {
        return (
            <Card variant="outlined">
                <CardContent>
                    <Typography
                        variant="subtitle2"
                        color="text.secondary"
                        gutterBottom
                    >
                        Social vs alone
                    </Typography>

                    <Stack spacing={1}>
                        <Stack direction="row" justifyContent="space-between">
                            <Typography variant="body2">Social</Typography>
                            <Typography variant="body2">
                                {minutesToHM(socialMinutes)} (
                                {socialPercent.toFixed(0)}%)
                            </Typography>
                        </Stack>
                        <LinearProgress
                            variant="determinate"
                            value={socialPercent}
                        />

                        <Stack direction="row" justifyContent="space-between">
                            <Typography variant="body2">Alone</Typography>
                            <Typography variant="body2">
                                {minutesToHM(aloneMinutes)} (
                                {alonePercent.toFixed(0)}%)
                            </Typography>
                        </Stack>
                        <LinearProgress
                            variant="determinate"
                            value={alonePercent}
                        />
                    </Stack>
                </CardContent>
            </Card>
        );
    }
};

export default DaySummaryComponent;

function SummaryText({ summaryText }: { summaryText: string }) {
    return (
        <Card variant="outlined">
            <CardContent>
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
    socialPercent,
    alonePercent,
}: {
    totalMinutes: number;
    totalImages: number;
    socialPercent: number;
    alonePercent: number;
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

                    <Stack direction="row" spacing={1} mt={1} flexWrap="wrap">
                        <Chip
                            size="small"
                            label={`Social ${socialPercent.toFixed(0)}%`}
                            color="primary"
                            variant="outlined"
                        />
                        <Chip
                            size="small"
                            label={`Alone ${alonePercent.toFixed(0)}%`}
                            variant="outlined"
                        />
                    </Stack>
                </Box>
            </CardContent>
        </Card>
    );
};

function Timeline({ daySummary }: { daySummary: DaySummary }) {
    return (
        <Card variant="outlined">
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
                            width: '100%',
                            pt: 1,
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
        <Card variant="outlined">
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

function FoodDrinkSummary({
    foodDrinkMinutes,
    foodDrinkSummary,
    foodDrinkSegments,
}: {
    foodDrinkMinutes: number;
    foodDrinkSummary: string;
    foodDrinkSegments: SummarySegment[];
}) {
    return (
        <Card variant="outlined" sx={{ height: '100%' }}>
            <CardContent
                sx={{
                    display: 'flex',
                    flexDirection: 'column',
                    height: '100%',
                }}
            >
                <Typography
                    variant="subtitle2"
                    color="text.secondary"
                    gutterBottom
                >
                    Food & drink
                </Typography>

                <Typography variant="body2">
                    Time: <strong>{minutesToHM(foodDrinkMinutes)}</strong>
                </Typography>
                <Typography
                    variant="body2"
                    sx={{ mt: 1, mb: 2, whiteSpace: 'pre-line' }}
                >
                    {foodDrinkSummary ||
                        'No food or drink activities detected.'}
                </Typography>
                <Stack
                    direction="row"
                    spacing={1}
                    sx={{
                        overflow: 'auto',
                        maxWidth: '70dvw',
                        mb: 2,
                        pb: 2,
                        flexGrow: 1,
                    }}
                >
                    {foodDrinkSegments.map((segment, index) => (
                        <React.Fragment key={index}>
                            <Typography
                                variant="body2"
                                sx={{ alignSelf: 'center' }}
                            >
                                {segment.startTime} {segment.endTime}
                            </Typography>
                            {segment.representativeImages?.map(
                                (image, imgIndex) => (
                                    <ImageWithDate
                                        key={`${index}-${imgIndex}`}
                                        image={image}
                                        height={'220px'}
                                        fontSize={'12px'}
                                        disableDelete
                                    />
                                )
                            )}
                            <Divider orientation="vertical" flexItem />
                        </React.Fragment>
                    ))}
                </Stack>
            </CardContent>
        </Card>
    );
}

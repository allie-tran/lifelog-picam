import {
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    Grid,
    LinearProgress,
    Stack,
    Tooltip,
    Typography,
} from '@mui/material';
import { SummarySegment } from '@utils/types';
import { getDaySummary, processDate } from 'apis/process';
import { useSearchParams } from 'react-router';
import { useAppSelector } from 'reducers/hooks';
import useSWR from 'swr';
import 'utils/animation.css';
import { CategoryPieChart } from './CategoryChart';
import { CATEGORIES } from 'constants/activityColors';

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

const DaySummary = () => {
    const [searchParams, _] = useSearchParams();
    const date = searchParams.get('date');
    const deviceId = useAppSelector((state) => state.auth.deviceId) || '';

    const { data: daySummary, isLoading } = useSWR(
        { date, deviceId },
        () => (date ? getDaySummary(deviceId, date) : null),
        {
            revalidateOnFocus: false,
        }
    );

    if (isLoading) {
        return <LinearProgress />;
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
        foodDrinkImages,
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
                <Grid size={4}>
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

                                <Stack
                                    direction="row"
                                    spacing={1}
                                    mt={1}
                                    flexWrap="wrap"
                                >
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
                </Grid>

                {/* Social vs alone */}
                <Grid size={4}>
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
                                <Stack
                                    direction="row"
                                    justifyContent="space-between"
                                >
                                    <Typography variant="body2">
                                        Social
                                    </Typography>
                                    <Typography variant="body2">
                                        {minutesToHM(socialMinutes)} (
                                        {socialPercent.toFixed(0)}%)
                                    </Typography>
                                </Stack>
                                <LinearProgress
                                    variant="determinate"
                                    value={socialPercent}
                                />

                                <Stack
                                    direction="row"
                                    justifyContent="space-between"
                                >
                                    <Typography variant="body2">
                                        Alone
                                    </Typography>
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
                </Grid>
                {/* Food & drink */}
                <Grid size={4}>
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
                                Time:{' '}
                                <strong>{minutesToHM(foodDrinkMinutes)}</strong>
                            </Typography>
                            <Typography
                                variant="body2"
                                color="text.secondary"
                                mb={2}
                            >
                                Images: {foodDrinkImages.length}
                            </Typography>
                        </CardContent>
                    </Card>
                </Grid>
                {/* Category breakdown */}
                {/* Activity categories */}
                <Grid size={6}>
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
                                <Typography
                                    variant="body2"
                                    color="text.secondary"
                                >
                                    No category data.
                                </Typography>
                            )}

                            <Stack
                                mt={4}
                                justifyContent="center"
                                alignItems="center"
                            >
                                <CategoryPieChart
                                    categoryMinutes={categoryMinutes}
                                    totalMinutes={totalMinutes}
                                />
                            </Stack>
                        </CardContent>
                    </Card>
                </Grid>
                <Grid size={6}>
                    <Card variant="outlined">
                        <CardContent>
                            {daySummary && (
                                <Typography variant="body1">
                                    {daySummary.summaryText ||
                                        'No summary available for this day.'}
                                </Typography>
                            )}
                        </CardContent>
                    </Card>
                </Grid>
                {/* Timeline */}
                <Grid size={12}>
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
                                        (
                                            segment: SummarySegment,
                                            index: number
                                        ) => (
                                            <Tooltip
                                                title={`${segment.activity}: ${segment.startTime} - ${segment.endTime}`}
                                                key={index}
                                            >
                                                <Box
                                                    sx={{
                                                        height: 48,
                                                        width: 10,
                                                        backgroundColor:
                                                            CATEGORIES[
                                                                segment.activity
                                                            ] || '#bdc3c7',
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
                </Grid>
            </Grid>

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
                Reset
            </Button>
        </Stack>
    );
};

export default DaySummary;

import {
    alpha,
    Box,
    Card,
    CardContent,
    Chip,
    Grid,
    LinearProgress,
    Skeleton,
    Stack,
    Tooltip,
    Typography,
} from '@mui/material';
import LocationOnIcon from '@mui/icons-material/LocationOn';
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward';
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward';
import FiberNewIcon from '@mui/icons-material/FiberNew';
import { getPeriodSummary } from 'apis/process';
import { CategoryPieChart } from 'components/charts/CategoryChart';
import ReactECharts from 'echarts-for-react';
import { useSearchParams } from 'react-router';
import useSWR from 'swr';
import { TrendItem, BioTrend } from '@utils/types';
import { SummaryText } from '../DaySummary/cards';
import { minutesToHM } from '../DaySummary/shared';

type PeriodKind = 'week' | 'month' | 'trip' | 'custom';

const trendIcon = (dir: string) =>
    dir === 'up' ? <ArrowUpwardIcon fontSize="small" />
        : dir === 'down' ? <ArrowDownwardIcon fontSize="small" />
        : dir === 'new' ? <FiberNewIcon fontSize="small" />
        : undefined;

const trendColor = (dir: string): 'success' | 'warning' | 'info' | 'default' =>
    dir === 'new' ? 'success' : dir === 'up' ? 'info' : dir === 'down' ? 'warning' : 'default';

function TrendsCard({ trends }: { trends: TrendItem[] }) {
    if (!trends?.length) return null;
    return (
        <Card variant="outlined">
            <CardContent>
                <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                    Changes vs previous period
                </Typography>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                    {trends.map((t, i) => (
                        <Chip
                            key={`${t.metric}-${i}`}
                            icon={trendIcon(t.direction)}
                            label={t.note}
                            size="small"
                            color={trendColor(t.direction)}
                            variant="outlined"
                        />
                    ))}
                </Stack>
            </CardContent>
        </Card>
    );
}

function BioTrendCard({ bio }: { bio: BioTrend }) {
    const series = bio.series || [];
    if (series.length < 2) return null;
    const dates = series.map((p) => p.date.slice(5));
    const option = {
        tooltip: { trigger: 'axis' },
        legend: { data: ['Sleep (h)', 'Steps', 'Avg HR'], textStyle: { color: '#999' } },
        grid: { left: 40, right: 40, top: 30, bottom: 30 },
        xAxis: { type: 'category', data: dates },
        yAxis: [
            { type: 'value', name: 'h / bpm', position: 'left' },
            { type: 'value', name: 'steps', position: 'right' },
        ],
        series: [
            {
                name: 'Sleep (h)', type: 'bar', yAxisIndex: 0,
                data: series.map((p) => (p.sleepMinutes != null ? +(p.sleepMinutes / 60).toFixed(1) : null)),
                itemStyle: { color: '#7e57c2' },
            },
            {
                name: 'Steps', type: 'line', yAxisIndex: 1, smooth: true,
                data: series.map((p) => p.stepCount ?? null),
                itemStyle: { color: '#26a69a' },
            },
            {
                name: 'Avg HR', type: 'line', yAxisIndex: 0, smooth: true,
                data: series.map((p) => p.avgHr ?? null),
                itemStyle: { color: '#ef5350' },
            },
        ],
    };
    return (
        <Card variant="outlined">
            <CardContent>
                <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                    Biometrics over the period
                </Typography>
                <ReactECharts option={option} style={{ height: 240 }} />
            </CardContent>
        </Card>
    );
}

/**
 * Multi-day period summary (week / month / trip / custom range). Rolls up the
 * per-day summaries in [start, end]; reuses the day-summary presentational
 * cards. Clicking a day drills down by setting ?date=.
 */
const PeriodSummaryView = ({
    device,
    kind,
    start,
    end,
}: {
    device: string;
    kind: PeriodKind;
    start: string;
    end: string;
}) => {
    const [searchParams, setSearchParams] = useSearchParams();

    const { data: period, isLoading } = useSWR(
        device && start && end
            ? { key: 'period-summary', device, kind, start, end }
            : null,
        () => getPeriodSummary(device, kind, start, end),
        {
            revalidateOnFocus: false,
            revalidateIfStale: false,
            shouldRetryOnError: false,
            refreshInterval: (data) => (data?.processing ? 3000 : 0),
        }
    );

    if (isLoading) {
        return <Skeleton width="100%" height={360} variant="rounded" />;
    }

    if (!period) {
        return (
            <Card variant="outlined" sx={{ backgroundColor: alpha('#333', 0.2) }}>
                <CardContent>
                    <Typography p={2} color="text.secondary" textAlign="center">
                        No summarized days in this range.
                    </Typography>
                </CardContent>
            </Card>
        );
    }

    const goToDay = (d: string) => {
        const next = new URLSearchParams(searchParams);
        next.set('date', d);
        setSearchParams(next);
    };

    return (
        <Stack spacing={2} padding={1}>
            <Stack direction="row" justifyContent="space-between" alignItems="flex-end">
                <Box>
                    <Typography variant="h6" fontWeight="bold">
                        {period.label}
                    </Typography>
                    <Typography variant="subtitle2" color="text.secondary">
                        {period.activeDays} active {period.activeDays === 1 ? 'day' : 'days'} ·{' '}
                        {minutesToHM(period.totalMinutes)} tracked · {period.totalImages} photos
                    </Typography>
                </Box>
                <Stack direction="row" alignItems="center" spacing={1}>
                    {period.processing ? (
                        <Tooltip title="This recap is out of date — a refresh is running in the background. It will update automatically.">
                            <Chip size="small" color="warning" variant="outlined" label="Updating…" />
                        </Tooltip>
                    ) : period.updated ? (
                        <Tooltip title="An underlying day changed since this recap was written — it will refresh shortly.">
                            <Chip size="small" color="warning" variant="outlined" label="Out of date" />
                        </Tooltip>
                    ) : null}
                    {period.processing && (
                        <LinearProgress sx={{ width: 120, alignSelf: 'center' }} />
                    )}
                </Stack>
            </Stack>

            {/* Day chips — drill down into any day of the period */}
            {period.dayDates.length > 0 && (
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                    {period.dayDates.map((d) => (
                        <Chip
                            key={d}
                            label={d.slice(5)}
                            size="small"
                            variant="outlined"
                            onClick={() => goToDay(d)}
                        />
                    ))}
                </Stack>
            )}

            <Grid container spacing={2}>
                <Grid size={{ xs: 12, md: 7 }}>
                    {period.processing && !period.summaryText ? (
                        <Card variant="outlined" sx={{ height: '100%' }}>
                            <CardContent>
                                <Stack spacing={1} alignItems="center" py={4}>
                                    <Typography color="text.secondary">
                                        Writing the recap…
                                    </Typography>
                                    <LinearProgress sx={{ width: '60%' }} />
                                </Stack>
                            </CardContent>
                        </Card>
                    ) : (
                        <SummaryText
                            summaryText={period.summaryText}
                            heading={
                                {
                                    week: 'Week Overview',
                                    month: 'Month Overview',
                                    trip: 'Trip Overview',
                                }[period.kind] ?? 'Period Overview'
                            }
                        />
                    )}
                </Grid>
                <Grid size={{ xs: 12, md: 5 }}>
                    <Card variant="outlined" sx={{ height: '100%' }}>
                        <CardContent>
                            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                                Activity Mix
                            </Typography>
                            <CategoryPieChart
                                categoryMinutes={period.categoryMinutes}
                                totalMinutes={period.totalMinutes}
                            />
                        </CardContent>
                    </Card>
                </Grid>

                {period.trends.length > 0 && (
                    <Grid size={12}>
                        <TrendsCard trends={period.trends} />
                    </Grid>
                )}

                {period.bioTrend && (period.bioTrend.series?.length ?? 0) >= 2 && (
                    <Grid size={12}>
                        <BioTrendCard bio={period.bioTrend} />
                    </Grid>
                )}

                {period.topLocations.length > 0 && (
                    <Grid size={12}>
                        <Card variant="outlined">
                            <CardContent>
                                <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                                    Places Visited
                                </Typography>
                                <Stack spacing={1}>
                                    {period.topLocations.slice(0, 12).map((loc) => (
                                        <Stack
                                            key={loc.name}
                                            direction="row"
                                            spacing={1}
                                            alignItems="center"
                                            justifyContent="space-between"
                                        >
                                            <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 0 }}>
                                                <LocationOnIcon fontSize="small" color="primary" />
                                                <Typography variant="body2" noWrap>
                                                    {loc.name}
                                                </Typography>
                                            </Stack>
                                            <Typography variant="caption" color="text.secondary" sx={{ flexShrink: 0 }}>
                                                {minutesToHM(loc.minutes)}
                                                {loc.days > 1 ? ` · ${loc.days} days` : ''}
                                            </Typography>
                                        </Stack>
                                    ))}
                                </Stack>
                            </CardContent>
                        </Card>
                    </Grid>
                )}
            </Grid>
        </Stack>
    );
};

export default PeriodSummaryView;

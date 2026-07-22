import { Container, IconButton, MenuItem, Stack, Tab, Tabs, TextField, Typography } from '@mui/material';
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft';
import ChevronRightIcon from '@mui/icons-material/ChevronRight';
import SensorHistory from 'components/meta/Biometrics';
import CustomDatePicker from 'components/temporal/CustomDatePicker';
import DaySummaryComponent from 'components/browse/DaySummary';
import PeriodSummaryView from 'components/browse/PeriodSummary';
import dayjs from 'dayjs';
import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router';
import { setDevice } from 'reducers/auth';
import { useAppDispatch } from 'reducers/hooks';
import useSWR from 'swr';
import '../App.css';
import { getAllDates } from '../apis/browsing';
import { getTrips } from '../apis/process';

type Scope = 'day' | 'week' | 'month' | 'trip' | 'custom';

// Monday-anchored ISO week bounds for a given date (no dayjs plugin needed).
const weekBounds = (d: dayjs.Dayjs): [string, string] => {
    const monday = d.subtract((d.day() + 6) % 7, 'day');
    return [monday.format('YYYY-MM-DD'), monday.add(6, 'day').format('YYYY-MM-DD')];
};

const shortRange = (start: string, end: string): string => {
    const s = dayjs(start);
    const e = dayjs(end);
    if (s.isSame(e, 'month')) return `${s.format('MMM D')} – ${e.format('D, YYYY')}`;
    return `${s.format('MMM D')} – ${e.format('MMM D, YYYY')}`;
};

function Insights() {
    const [searchParams] = useSearchParams();
    const date = searchParams.get('date');
    const device = searchParams.get('device') || '';

    const dispatch = useAppDispatch();
    const [scope, setScope] = useState<Scope>('day');
    const [customStart, setCustomStart] = useState('');
    const [customEnd, setCustomEnd] = useState('');
    const [tripIdx, setTripIdx] = useState(0);
    // Anchor date the week/month scopes page around; ‹ › shift it.
    const [anchor, setAnchor] = useState('');

    useEffect(() => {
        if (device) dispatch(setDevice(device));
    }, [device]);

    const { data: allDates } = useSWR(
        ['all-dates', device, date],
        async () => getAllDates(device),
        { revalidateOnFocus: false }
    );

    const { data: trips } = useSWR(
        scope === 'trip' && device ? ['trips', device] : null,
        async () => getTrips(device),
        { revalidateOnFocus: false }
    );

    // Reference date: the selected date, else the latest available.
    const refDate = date || allDates?.[allDates.length - 1] || dayjs().format('YYYY-MM-DD');
    // Sync the paging anchor whenever the selected/latest date changes.
    useEffect(() => {
        setAnchor(refDate);
    }, [refDate]);
    const ref = dayjs(anchor || refDate);

    // Seed the custom range from the reference week the first time it's opened.
    useEffect(() => {
        if (scope === 'custom' && !customStart && !customEnd) {
            const [s, e] = weekBounds(ref);
            setCustomStart(s);
            setCustomEnd(e);
        }
    }, [scope]);

    // Clamp trip index when the trip list changes.
    useEffect(() => {
        if (trips && tripIdx > trips.length - 1) setTripIdx(0);
    }, [trips]);

    let periodProps: { start: string; end: string; kind: 'week' | 'month' | 'trip' | 'custom' } | null = null;
    let navLabel = '';
    if (scope === 'week') {
        const [s, e] = weekBounds(ref);
        periodProps = { start: s, end: e, kind: 'week' };
        navLabel = `Week of ${dayjs(s).format('MMM D, YYYY')}`;
    } else if (scope === 'month') {
        periodProps = {
            start: ref.startOf('month').format('YYYY-MM-DD'),
            end: ref.endOf('month').format('YYYY-MM-DD'),
            kind: 'month',
        };
        navLabel = ref.format('MMMM YYYY');
    } else if (scope === 'trip' && trips && trips[tripIdx]) {
        const t = trips[tripIdx];
        periodProps = { start: t.start, end: t.end, kind: 'trip' };
        navLabel = `${t.label} · ${shortRange(t.start, t.end)}`;
    } else if (scope === 'custom' && customStart && customEnd) {
        periodProps = { start: customStart, end: customEnd, kind: 'custom' };
    }

    // Prev/next paging per scope.
    const step = (dir: -1 | 1) => {
        if (scope === 'week') setAnchor(ref.add(dir * 7, 'day').format('YYYY-MM-DD'));
        else if (scope === 'month') setAnchor(ref.add(dir, 'month').format('YYYY-MM-DD'));
        else if (scope === 'trip' && trips) {
            setTripIdx((i) => Math.min(trips.length - 1, Math.max(0, i + dir)));
        }
    };
    const showNav = scope === 'week' || scope === 'month' || (scope === 'trip' && !!trips?.length);
    // Trips are ordered newest-first, so "previous" (older) is a higher index.
    const prevDisabled = scope === 'trip' && trips ? tripIdx >= trips.length - 1 : false;
    const nextDisabled = scope === 'trip' && trips ? tripIdx <= 0 : false;

    return (
        <Container>
            <Stack direction="row" spacing={2} width="100%" pl={1} alignItems="center" mb={2}>
                <CustomDatePicker
                    date={date}
                    allDates={allDates}
                    setPage={() => {}}
                    setHour={() => {}}
                />
            </Stack>

            <Tabs value={scope} onChange={(_, v) => setScope(v)} sx={{ mb: 2 }}>
                <Tab label="Day" value="day" />
                <Tab label="Week" value="week" />
                <Tab label="Month" value="month" />
                <Tab label="Trip" value="trip" />
                <Tab label="Custom" value="custom" />
            </Tabs>

            {showNav && (
                <Stack direction="row" spacing={1} alignItems="center" mb={2} pl={1}>
                    <IconButton size="small" onClick={() => step(-1)} disabled={prevDisabled}>
                        <ChevronLeftIcon />
                    </IconButton>
                    <Typography variant="subtitle1" fontWeight="medium" sx={{ minWidth: 220, textAlign: 'center' }}>
                        {navLabel || '—'}
                    </Typography>
                    <IconButton size="small" onClick={() => step(1)} disabled={nextDisabled}>
                        <ChevronRightIcon />
                    </IconButton>
                    {scope === 'trip' && trips && trips.length > 0 && (
                        <Typography variant="caption" color="text.secondary" ml={1}>
                            {tripIdx + 1} / {trips.length}
                        </Typography>
                    )}
                </Stack>
            )}

            {scope === 'trip' && trips && trips.length === 0 && (
                <Typography variant="body2" color="text.secondary" mb={2} pl={1}>
                    No trips detected. Label your home location to sharpen detection.
                </Typography>
            )}

            {scope === 'custom' && (
                <Stack direction="row" spacing={2} mb={2} pl={1}>
                    <TextField
                        label="Start"
                        type="date"
                        size="small"
                        value={customStart}
                        onChange={(e) => setCustomStart(e.target.value)}
                        InputLabelProps={{ shrink: true }}
                    />
                    <TextField
                        label="End"
                        type="date"
                        size="small"
                        value={customEnd}
                        onChange={(e) => setCustomEnd(e.target.value)}
                        InputLabelProps={{ shrink: true }}
                    />
                </Stack>
            )}

            {scope === 'day' ? (
                <>
                    <SensorHistory />
                    <DaySummaryComponent />
                </>
            ) : periodProps ? (
                <PeriodSummaryView
                    device={device}
                    kind={periodProps.kind}
                    start={periodProps.start}
                    end={periodProps.end}
                />
            ) : null}
        </Container>
    );
}

export default Insights;

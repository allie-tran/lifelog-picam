import { Container, MenuItem, Stack, Tab, Tabs, TextField, Typography } from '@mui/material';
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

function Insights() {
    const [searchParams] = useSearchParams();
    const date = searchParams.get('date');
    const device = searchParams.get('device') || '';

    const dispatch = useAppDispatch();
    const [scope, setScope] = useState<Scope>('day');
    const [customStart, setCustomStart] = useState('');
    const [customEnd, setCustomEnd] = useState('');
    const [tripIdx, setTripIdx] = useState(0);

    const { data: trips } = useSWR(
        scope === 'trip' && device ? ['trips', device] : null,
        async () => getTrips(device),
        { revalidateOnFocus: false }
    );

    useEffect(() => {
        if (device) dispatch(setDevice(device));
    }, [device]);

    const { data: allDates } = useSWR(
        ['all-dates', device, date],
        async () => getAllDates(device),
        { revalidateOnFocus: false }
    );

    // Reference date for week/month scopes: the selected date, else latest.
    const refDate = date || allDates?.[allDates.length - 1] || dayjs().format('YYYY-MM-DD');
    const ref = dayjs(refDate);

    // Seed the custom range from the reference week the first time it's opened.
    useEffect(() => {
        if (scope === 'custom' && !customStart && !customEnd) {
            const [s, e] = weekBounds(ref);
            setCustomStart(s);
            setCustomEnd(e);
        }
    }, [scope]);

    let periodProps: { start: string; end: string; kind: 'week' | 'month' | 'trip' | 'custom' } | null = null;
    if (scope === 'week') {
        const [s, e] = weekBounds(ref);
        periodProps = { start: s, end: e, kind: 'week' };
    } else if (scope === 'month') {
        periodProps = {
            start: ref.startOf('month').format('YYYY-MM-DD'),
            end: ref.endOf('month').format('YYYY-MM-DD'),
            kind: 'month',
        };
    } else if (scope === 'trip' && trips && trips[tripIdx]) {
        const t = trips[tripIdx];
        periodProps = { start: t.start, end: t.end, kind: 'trip' };
    } else if (scope === 'custom' && customStart && customEnd) {
        periodProps = { start: customStart, end: customEnd, kind: 'custom' };
    }

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

            {scope === 'trip' && (
                <Stack mb={2} pl={1}>
                    {trips && trips.length > 0 ? (
                        <TextField
                            select
                            label="Trip"
                            size="small"
                            value={tripIdx}
                            onChange={(e) => setTripIdx(Number(e.target.value))}
                            sx={{ minWidth: 280 }}
                        >
                            {trips.map((t, i) => (
                                <MenuItem key={`${t.start}-${t.end}`} value={i}>
                                    {t.label} · {t.start} → {t.end} ({t.days}d)
                                </MenuItem>
                            ))}
                        </TextField>
                    ) : (
                        <Typography variant="body2" color="text.secondary">
                            {trips ? 'No trips detected. Label your home location to sharpen detection.' : 'Detecting trips…'}
                        </Typography>
                    )}
                </Stack>
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

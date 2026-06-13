import {
    Alert,
    Box,
    Container,
    IconButton,
    Snackbar,
    Stack,
    Tooltip,
} from '@mui/material';
import SyncIcon from '@mui/icons-material/Sync';
import { GPSData, ImageObject, ResultSegment } from '@utils/types';
import { getGPSByDate, GpsTrackData } from 'apis/process';
import CurrentStatus from 'components/meta/CurrentStatus';
import CustomDatePicker from 'components/temporal/CustomDatePicker';
import DayNavBar, { SegmentSelection } from 'components/browse/DayNavBar';
import DeleteRange from 'components/browse/DeleteRange';
import GpsTrack from 'components/spatial/GpsTrack';
import LifelogEvent, { LifelogEventSkeleton } from 'components/browse/LifelogEvent';
import dayjs from 'dayjs';
import React, { useEffect } from 'react';
import { useSearchParams } from 'react-router';
import { setDevice } from 'reducers/auth';
import { setLoading } from 'reducers/feedback';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import useSWR from 'swr';
import { AccessLevel } from 'types/auth';
import '../App.css';
import {
    deleteImages,
    getAllDates,
    getDayNavSegments,
    getDayStops,
    getImagesBySegment,
    resyncDay,
} from '../apis/browsing';
import { ImageZoom } from 'components/image/ImageZoom';

function MainPage() {
    const [searchParams, setSearchParams] = useSearchParams();
    const today = dayjs().format('YYYY-MM-DD');
    const date = searchParams.get('date');
    const device = searchParams.get('device') || '';
    const segmentParam = searchParams.get('segment');

    const selectedSegmentId: SegmentSelection | null = (() => {
        if (!segmentParam) return null;
        if (segmentParam === 'unsegmented') return 'unsegmented';
        if (segmentParam.includes(','))
            return segmentParam.split(',').map(Number);
        return Number(segmentParam);
    })();

    const setSegment = React.useCallback(
        (id: SegmentSelection | null) => {
            setSearchParams((prev) => {
                const next = new URLSearchParams(prev);
                if (id === null) next.delete('segment');
                else if (Array.isArray(id)) next.set('segment', id.join(','));
                else next.set('segment', String(id));
                return next;
            });
        },
        [setSearchParams]
    );

    const { deviceAccess } = useAppSelector((state) => state.auth);
    const dispatch = useAppDispatch();

    useEffect(() => {
        if (device) dispatch(setDevice(device));
    }, [device]);

    const isAuthorised =
        deviceAccess === AccessLevel.ADMIN ||
        deviceAccess === AccessLevel.OWNER;

    // Full-day GPS track (unchanged)
    const { data: gpsData } = useSWR(
        ['gps-track', device, date, deviceAccess],
        async (): Promise<GpsTrackData> => {
            if (isAuthorised) return getGPSByDate(device, date || '');
            return { rawGps: [], imageGps: [] };
        },
        {
            revalidateOnFocus: false,
            refreshInterval: date === today ? 3 * 60 * 1000 : 0,
        }
    );

    // Lightweight segment metadata for DayNavBar
    const { data: navSegments } = useSWR(
        date && device && isAuthorised ? ['day-nav', device, date] : null,
        () => getDayNavSegments(device, date || ''),
        {
            revalidateOnFocus: false,
            refreshInterval: date === today ? 60 * 1000 : 0,
        }
    );

    // Auto-select first segment when nav data loads and nothing is selected
    useEffect(() => {
        if (selectedSegmentId !== null) return;
        if (!navSegments?.length) return;
        // today → most recent first (last in array); past → earliest (first)
        const pick =
            date === today
                ? navSegments[navSegments.length - 1]
                : navSegments[0];
        if (pick?.segmentId != null) setSegment(pick.segmentId);
    }, [navSegments]); // eslint-disable-line react-hooks/exhaustive-deps

    // Keep only device + date when navigating to a new date/device
    useEffect(() => {
        setSearchParams(
            (prev) => {
                const d = prev.get('device');
                const dt = prev.get('date');
                const next = new URLSearchParams();
                if (d) next.set('device', d);
                if (dt) next.set('date', dt);
                return next;
            },
            { replace: true }
        );
    }, [date, device]); // eslint-disable-line react-hooks/exhaustive-deps

    // Segment images — fetched on demand; arrays = parallel fetch + merge
    const { data, mutate, isLoading, isValidating } = useSWR(
        selectedSegmentId !== null && date && device && isAuthorised
            ? [
                  'segment',
                  device,
                  date,
                  Array.isArray(selectedSegmentId)
                      ? selectedSegmentId.join(',')
                      : selectedSegmentId,
              ]
            : null,
        async () => {
            const d = date || '';
            if (Array.isArray(selectedSegmentId)) {
                const results = await Promise.all(
                    selectedSegmentId.map((id) =>
                        getImagesBySegment(device, d, id)
                    )
                );
                return {
                    segments: results.flatMap((r) => r.segments),
                    gps: results.flatMap((r) => r.gps),
                };
            }
            return getImagesBySegment(
                device,
                d,
                selectedSegmentId as number | 'unsegmented'
            );
        },
        {
            revalidateOnFocus: false,
            keepPreviousData: true,
            refreshInterval: date === today ? 3 * 60 * 1000 : 0,
        }
    );

    const { data: allDates } = useSWR(
        ['all-dates', device, date],
        () => getAllDates(device),
        { revalidateOnFocus: false }
    );

    // No date in the URL → land on the latest available day (ISO dates sort
    // chronologically, so the max is the most recent).
    useEffect(() => {
        if (date) return;
        if (!allDates?.length) return;
        const sorted = [...allDates].sort();
        const latest = sorted[sorted.length - 1];
        if (!latest) return;
        setSearchParams(
            (prev) => {
                const next = new URLSearchParams(prev);
                next.set('date', latest);
                return next;
            },
            { replace: true }
        );
    }, [date, allDates]); // eslint-disable-line react-hooks/exhaustive-deps

    const { data: dayStops } = useSWR(
        date && device && isAuthorised ? ['day-stops', device, date] : null,
        () => getDayStops(device, date || ''),
        {
            revalidateOnFocus: false,
            refreshInterval: date === today ? 3 * 60 * 1000 : 0,
        }
    );

    // Recent (unsegmented) — always shown at top for today
    const { data: recentData, mutate: mutateRecent } = useSWR(
        date === today && device && isAuthorised
            ? ['unsegmented', device, date]
            : null,
        () => getImagesBySegment(device, date || '', 'unsegmented'),
        { revalidateOnFocus: false, refreshInterval: 60 * 1000 }
    );
    const isToday = date === today;

    // For today, show most recent first: newest image at the top of each event,
    // and newest event before older ones. Past days keep chronological order.
    const orderForView = React.useCallback(
        (segs: ResultSegment[]): ResultSegment[] => {
            if (!isToday) return segs;
            const newestFirst = (a: ImageObject, b: ImageObject) =>
                dayjs(b.timestamp).valueOf() - dayjs(a.timestamp).valueOf();
            return segs
                .map((s) => ({ ...s, images: [...s.images].sort(newestFirst) }))
                .sort((a, b) => {
                    const at = a.images[0]?.timestamp;
                    const bt = b.images[0]?.timestamp;
                    return dayjs(bt).valueOf() - dayjs(at).valueOf();
                });
        },
        [isToday]
    );

    const recentSegments = orderForView(recentData?.segments ?? []);
    const hasRecent = isToday && recentSegments.length > 0;

    // "Recent" (unsegmented, newest-of-all) belongs with the most recent
    // location. Show it as a block on top only when that last segment is
    // selected; older locations don't show it. The Recent nav pill instead
    // selects 'unsegmented' and shows the same images in the main list.
    const lastNavSegmentId = navSegments?.length
        ? navSegments[navSegments.length - 1].segmentId
        : null;
    const showRecent =
        hasRecent &&
        lastNavSegmentId != null &&
        (Array.isArray(selectedSegmentId)
            ? selectedSegmentId.includes(lastNavSegmentId)
            : selectedSegmentId === lastNavSegmentId);

    const imageGps: GPSData[] = gpsData?.imageGps ?? [];
    const segments = orderForView(data?.segments || []);

    const activeSegmentIds = React.useMemo(() => {
        if (typeof selectedSegmentId === 'number')
            return new Set([selectedSegmentId]);
        if (Array.isArray(selectedSegmentId)) return new Set(selectedSegmentId);
        return undefined;
    }, [selectedSegmentId]);

    const deleteRow = async (imagePaths: string[]) => {
        dispatch(setLoading(true));
        await deleteImages(device, imagePaths);
        await Promise.all([mutate(), mutateRecent?.()]);
        dispatch(setLoading(false));
    };

    const [resyncing, setResyncing] = React.useState(false);
    const [resyncError, setResyncError] = React.useState<string | null>(null);
    const handleResync = async () => {
        if (!device || !date || resyncing) return;
        setResyncing(true);
        try {
            await resyncDay(device, date);
        } catch (e) {
            setResyncError('Resync failed — check server logs');
        } finally {
            setResyncing(false);
        }
    };

    return (
        <>
            <Stack spacing={2} alignItems="center" sx={{ padding: 2 }} id="app">
                <Container>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Box sx={{ flex: 1 }}>
                            <CustomDatePicker date={date} allDates={allDates} />
                        </Box>
                        {isAuthorised && date && (
                            <Tooltip title="Re-sync segmentation (preserves LLM annotations)">
                                <span>
                                    <IconButton
                                        onClick={handleResync}
                                        disabled={resyncing}
                                        size="small"
                                        sx={{
                                            mt: 1,
                                            animation: resyncing
                                                ? 'spin 1s linear infinite'
                                                : 'none',
                                            '@keyframes spin': {
                                                from: {
                                                    transform: 'rotate(0deg)',
                                                },
                                                to: {
                                                    transform: 'rotate(360deg)',
                                                },
                                            },
                                        }}
                                    >
                                        <SyncIcon fontSize="small" />
                                    </IconButton>
                                </span>
                            </Tooltip>
                        )}
                    </Box>
                    {(!date || date === today) && (
                        <CurrentStatus device={device} />
                    )}
                </Container>

                <Box sx={{ width: '100%' }}>
                    <DayNavBar
                        navSegments={navSegments}
                        selectedSegmentId={selectedSegmentId}
                        onSelectSegment={setSegment}
                        hasRecent={hasRecent}
                    />
                </Box>

                {!isLoading &&
                    segments.length === 0 &&
                    selectedSegmentId !== null &&
                    isAuthorised && (
                        <div>No images found for this segment.</div>
                    )}

                <Stack
                    sx={{ width: '100%', height: 'calc(100dvh - 200px)' }}
                    direction="row"
                    spacing={2}
                >
                    <GpsTrack
                        imageGps={imageGps}
                        currentTrack={data?.gps || []}
                        segments={segments}
                        activeSegmentIds={activeSegmentIds}
                        dayStops={dayStops}
                    />
                    <Stack
                        sx={{
                            width: 'calc(100% - 400px)',
                            height: '100%',
                            overflowY: 'auto',
                            pr: 1,
                            justifyContent: 'flex-start',
                            alignItems: 'flex-start',
                            opacity: isValidating && !isLoading ? 0.4 : 1,
                            transition: 'opacity 0.2s ease',
                            pointerEvents:
                                isValidating && !isLoading ? 'none' : 'auto',
                        }}
                    >
                        {/* Recent — unsegmented images for today; shown only
                            with the most recent location selected */}
                        {showRecent && (
                            <Box sx={{ width: '100%', mb: 1 }}>
                                <Box
                                    sx={{
                                        fontWeight: 700,
                                        fontSize: '0.75rem',
                                        color: 'text.secondary',
                                        mb: 0.5,
                                        textTransform: 'uppercase',
                                        letterSpacing: 1,
                                    }}
                                >
                                    Recent
                                </Box>
                                {recentSegments.map(
                                    (segment, index) =>
                                        segment.images.length > 0 && (
                                            <LifelogEvent
                                                key={`recent-${index}`}
                                                segment={segment.images}
                                                location={segment.location}
                                                gpsList={segment.gps}
                                                onChange={() =>
                                                    mutateRecent?.()
                                                }
                                                deleteRow={deleteRow}
                                            />
                                        )
                                )}
                                <DeleteRange
                                    onDelete={() => mutate()}
                                    date={date || dayjs().format('YYYY-MM-DD')}
                                />
                            </Box>
                        )}
                        {isLoading &&
                            Array.from({ length: 5 }).map((_, index) => (
                                <LifelogEventSkeleton key={index} />
                            ))}
                        {segments.map((segment, index) => {
                            if (segment.images.length === 0) return null;
                            return (
                                <LifelogEvent
                                    key={index}
                                    segment={segment.images}
                                    location={segment.location}
                                    gpsList={segment.gps}
                                    onChange={() => {
                                        dispatch(setLoading(true));
                                        mutate().then(() =>
                                            dispatch(setLoading(false))
                                        );
                                    }}
                                    deleteRow={deleteRow}
                                />
                            );
                        })}
                    </Stack>
                </Stack>
            </Stack>
            <ImageZoom onDelete={() => mutate()} />
            <Snackbar
                open={resyncError !== null}
                autoHideDuration={5000}
                onClose={() => setResyncError(null)}
            >
                <Alert severity="error" onClose={() => setResyncError(null)}>
                    {resyncError}
                </Alert>
            </Snackbar>
        </>
    );
}

export default MainPage;

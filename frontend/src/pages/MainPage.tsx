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
import { setLoading, showNotification } from 'reducers/feedback';
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

    // Scrollspy: segment currently at the top of the image list, mirrored on
    // the timeline so you always know where you are. Thumbnails lazy-load, so
    // rendering a whole location at once stays cheap.
    const [viewingSegmentId, setViewingSegmentId] = React.useState<
        number | null
    >(null);
    const listRef = React.useRef<HTMLDivElement | null>(null);

    // Forward paging: a single pick renders that segment then loads later ones
    // as you scroll; a location (array) pages through its own segments.
    const SEGMENT_PAGE = 4;
    const [visibleCount, setVisibleCount] = React.useState(SEGMENT_PAGE);
    const selectionKey = Array.isArray(selectedSegmentId)
        ? selectedSegmentId.join(',')
        : String(selectedSegmentId);
    useEffect(() => {
        setVisibleCount(Array.isArray(selectedSegmentId) ? SEGMENT_PAGE : 1);
        listRef.current?.scrollTo({ top: 0 });
    }, [selectionKey]); // eslint-disable-line react-hooks/exhaustive-deps

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

    // Chronological segment ids for the day, to page forward from any pick.
    const orderedIds = React.useMemo(
        () =>
            (navSegments ?? [])
                .map((s) => s.segmentId)
                .filter((id): id is number => id != null),
        [navSegments]
    );

    // Resolve selection into the ordered ids to page through. Both a single
    // segment and a location/mixed cell (array) page forward from their first
    // segment through the rest of the day, so scrolling always continues.
    const playlistIds = React.useMemo<number[]>(() => {
        const first = Array.isArray(selectedSegmentId)
            ? selectedSegmentId[0]
            : typeof selectedSegmentId === 'number'
              ? selectedSegmentId
              : null;
        if (first == null) return [];
        const i = orderedIds.indexOf(first);
        return i >= 0
            ? orderedIds.slice(i)
            : Array.isArray(selectedSegmentId)
              ? selectedSegmentId
              : [first];
    }, [selectedSegmentId, orderedIds]);

    const pageIds = playlistIds.slice(0, visibleCount);
    const hasMoreSegments = visibleCount < playlistIds.length;

    // Segment images — paged through playlistIds; thumbnails lazy-load so each
    // page stays light. 'unsegmented' (Recent) is a single fetch.
    const { data, mutate, isLoading, isValidating } = useSWR(
        selectedSegmentId !== null && date && device && isAuthorised
            ? [
                  'segment',
                  device,
                  date,
                  selectedSegmentId === 'unsegmented'
                      ? 'unsegmented'
                      : pageIds.join(','),
              ]
            : null,
        async () => {
            const d = date || '';
            if (selectedSegmentId === 'unsegmented') {
                return getImagesBySegment(device, d, 'unsegmented');
            }
            const results = await Promise.all(
                pageIds.map((id) => getImagesBySegment(device, d, id))
            );
            return {
                segments: results.flatMap((r) => r.segments),
                gps: results.flatMap((r) => r.gps),
            };
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
    const { data: recentData, error: recentError, mutate: mutateRecent } = useSWR(
        date === today && device && isAuthorised
            ? ['unsegmented', device, date]
            : null,
        () => getImagesBySegment(device, date || '', 'unsegmented'),
        { revalidateOnFocus: false, refreshInterval: 60 * 1000 }
    );
    const isToday = date === today;

    // The main list is always chronological for consistency. Only the "Recent"
    // block shows newest-first (newest image atop each event, newest event first).
    const newestFirst = React.useCallback(
        (segs: ResultSegment[]): ResultSegment[] => {
            const byNewest = (a: ImageObject, b: ImageObject) =>
                dayjs(b.timestamp).valueOf() - dayjs(a.timestamp).valueOf();
            return segs
                .map((s) => ({ ...s, images: [...s.images].sort(byNewest) }))
                .sort((a, b) => {
                    const at = a.images[0]?.timestamp;
                    const bt = b.images[0]?.timestamp;
                    return dayjs(bt).valueOf() - dayjs(at).valueOf();
                });
        },
        []
    );

    const recentSegments = newestFirst(recentData?.segments ?? []);
    const hasRecent = isToday && recentSegments.length > 0;

    // Auto-select when nothing is chosen: prefer Recent (unsegmented), else the
    // newest segment. On today, wait for the recent fetch before deciding.
    useEffect(() => {
        if (selectedSegmentId !== null) return;
        if (!navSegments?.length) return;
        // Wait for the recent fetch only while it's still in flight. If it
        // errored, treat it as "no recent" and fall through to latest segment.
        if (isToday && recentData === undefined && !recentError) return;
        if (hasRecent) {
            setSegment('unsegmented');
            return;
        }
        const newest = navSegments[navSegments.length - 1];
        if (newest?.segmentId != null) setSegment(newest.segmentId);
    }, [navSegments, recentData, recentError]); // eslint-disable-line react-hooks/exhaustive-deps

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
    const segments = data?.segments || [];
    // Stable signature of the rendered segment set, to re-arm the scrollspy
    // only when the segments actually change (not on every render).
    const segmentsKey = segments.map((s) => s.segmentId).join(',');

    const activeSegmentIds = React.useMemo(() => {
        if (typeof selectedSegmentId === 'number')
            return new Set([selectedSegmentId]);
        if (Array.isArray(selectedSegmentId)) return new Set(selectedSegmentId);
        return undefined;
    }, [selectedSegmentId]);

    // Scrollspy — track the segment nearest the top of the list and surface it
    // on the timeline. Re-arms whenever the rendered segment set changes.
    useEffect(() => {
        const root = listRef.current;
        if (!root) return;
        const els = Array.from(
            root.querySelectorAll<HTMLElement>('[data-seg-id]')
        );
        if (!els.length) return;
        const tops = new Map<Element, number>();
        const obs = new IntersectionObserver(
            (entries) => {
                for (const e of entries) {
                    if (e.isIntersecting)
                        tops.set(e.target, e.boundingClientRect.top);
                    else tops.delete(e.target);
                }
                const visible = Array.from(tops.entries());
                if (!visible.length) return;
                const [topEl] = visible.reduce((a, b) =>
                    b[1] < a[1] ? b : a
                );
                const id = Number((topEl as HTMLElement).dataset.segId);
                if (!Number.isNaN(id)) setViewingSegmentId(id);
            },
            { root, threshold: 0 }
        );
        els.forEach((el) => obs.observe(el));
        return () => obs.disconnect();
    }, [segmentsKey]); // eslint-disable-line react-hooks/exhaustive-deps

    // Infinite scroll — load the next page of segments as the sentinel nears
    // the bottom of the list.
    const loadMoreRef = React.useRef<HTMLDivElement | null>(null);
    useEffect(() => {
        if (!hasMoreSegments || isValidating) return;
        const root = listRef.current;
        const el = loadMoreRef.current;
        if (!root || !el) return;
        const obs = new IntersectionObserver(
            (entries) => {
                if (entries[0].isIntersecting)
                    setVisibleCount((c) => c + SEGMENT_PAGE);
            },
            { root, rootMargin: '400px' }
        );
        obs.observe(el);
        return () => obs.disconnect();
    }, [hasMoreSegments, isValidating, segmentsKey]); // eslint-disable-line react-hooks/exhaustive-deps

    const deleteRow = async (imagePaths: string[]) => {
        const toRemove = new Set(imagePaths);
        // Optimistically drop the images from the cached segments so they vanish
        // from the UI immediately; SWR rolls back if the request fails.
        const removeFromData = (d: typeof data): NonNullable<typeof data> =>
            d
                ? {
                      ...d,
                      segments: d.segments
                          .map((s) => ({
                              ...s,
                              images: s.images.filter(
                                  (img) => !toRemove.has(img.imagePath)
                              ),
                          }))
                          .filter((s) => s.images.length > 0),
                  }
                : { segments: [], gps: [] };
        try {
            await mutate(
                async () => {
                    await deleteImages(device, imagePaths);
                    return undefined; // fall through to revalidation below
                },
                {
                    optimisticData: removeFromData,
                    rollbackOnError: true,
                    revalidate: true,
                    populateCache: false,
                }
            );
            await mutateRecent?.();
        } catch (e) {
            // Rolled back to the previous cache; surface the failure.
            dispatch(
                showNotification({
                    message: 'Delete failed — restored images',
                    type: 'error',
                })
            );
        }
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
                        viewingSegmentId={viewingSegmentId}
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
                        ref={listRef}
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
                                    onDelete={deleteRow}
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
                                <Box
                                    key={index}
                                    data-seg-id={segment.segmentId}
                                    sx={{ width: '100%' }}
                                >
                                    <LifelogEvent
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
                                </Box>
                            );
                        })}
                        {hasMoreSegments && (
                            <Box ref={loadMoreRef} sx={{ width: '100%' }}>
                                <LifelogEventSkeleton />
                            </Box>
                        )}
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

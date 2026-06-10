import {
    Button,
    Container,
    Pagination,
    Stack,
    Typography,
} from '@mui/material';
import { GPSData } from '@utils/types';
import { getGPSByDate } from 'apis/process';
import CurrentStatus from 'components/CurrentStatus';
import CustomDatePicker from 'components/CustomDatePicker';
import DeleteRange from 'components/DeleteRange';
import GpsTrack from 'components/GpsTrack';
import LifelogEvent from 'components/LifelogEvent';
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
    getImagesByHour
} from '../apis/browsing';
import { ImageZoom } from '../components/ImageZoom';

function MainPage() {
    const [searchParams, _] = useSearchParams();
    const today = dayjs().format('YYYY-MM-DD');
    const date = searchParams.get('date');
    const device = searchParams.get('device') || '';

    const { deviceAccess } = useAppSelector((state) => state.auth);
    const [page, setPage] = React.useState(1);
    const [hour, setHour] = React.useState<number | null>(null);

    const dispatch = useAppDispatch();

    useEffect(() => {
        if (device) dispatch(setDevice(device));
    }, [device]);

    const { data, mutate } = useSWR(
        [page, date, hour, device, deviceAccess],
        async () => {
            if (
                deviceAccess === AccessLevel.ADMIN ||
                deviceAccess === AccessLevel.OWNER
            ) {
                setHour(hour || 0);
                return await getImagesByHour(
                    device,
                    date || '',
                    hour || 0,
                    page
                );
            } else {
                return {
                    images: [],
                    segments: [],
                    available_hours: [],
                    date: date || '',
                    total_pages: 1,
                    gps: [] as GPSData[],
                };
            }
        },
        {
            revalidateOnFocus: false,
            refreshInterval: date === today ? 3 * 60 * 1000 : 0,
        }
    );

    const { data: allDates } = useSWR(
        ['all-dates', device, date],
        async () => {
            const allDates = await getAllDates(device);
            return allDates;
        },
        {
            revalidateOnFocus: false,
        }
    );

    const { data: gpsTrack } = useSWR(
        ['gps-track', device, date, deviceAccess],
        async () => {
            if (
                deviceAccess === AccessLevel.ADMIN ||
                deviceAccess === AccessLevel.OWNER
            ) {
                const data = await getGPSByDate(device, date || '');
                console.log('GPS data:', data);
                return data;
            } else {
                console.warn(
                    'User does not have access to GPS data',
                    deviceAccess
                );
                return [] as GPSData[];
            }
        },
        {
            revalidateOnFocus: false,
            refreshInterval: date === today ? 3 * 60 * 1000 : 0,
        }
    );

    const images = data?.images;
    const segments = data?.segments || [];
    const availableHours = data?.available_hours || [];

    useEffect(() => {
        setPage(1);
    }, [date, device]);

    useEffect(() => {
        if (availableHours.length > 0 && !availableHours.includes(hour || 0)) {
            setHour(availableHours[0]);
        }
    }, [data, availableHours, hour]);

    const deleteRow = async (imagePaths: string[]) => {
        dispatch(setLoading(true));
        await deleteImages(device, imagePaths);
        await mutate();
        dispatch(setLoading(false));
    };

    return (
        <>
            <Stack spacing={2} alignItems="center" sx={{ padding: 2 }} id="app">
                <Container>
                    <CustomDatePicker
                        date={date}
                        setPage={setPage}
                        setHour={setHour}
                        allDates={allDates}
                    />
                    {(!date || date === today) && (
                        <CurrentStatus device={device} />
                    )}
                </Container>
                {availableHours.length > 0 && (
                    <Typography
                        variant="h6"
                        color="primary"
                        sx={{ alignSelf: 'flex-start', pt: 2 }}
                    >
                        Available Hours
                    </Typography>
                )}
                <Stack
                    direction="row"
                    spacing={1}
                    sx={{
                        width: '100%',
                        flexWrap: 'wrap',
                        pb: 2,
                    }}
                    useFlexGap
                >
                    {availableHours.map((h) => (
                        <Button
                            key={h}
                            variant={hour === h ? 'contained' : 'outlined'}
                            onClick={() => {
                                setHour(h === hour ? null : h);
                                setPage(1);
                            }}
                        >
                            {h}:00
                        </Button>
                    ))}
                </Stack>
                <DeleteRange
                    onDelete={() => mutate()}
                    date={date || dayjs().format('YYYY-MM-DD')}
                />
                {segments.length === 0 &&
                    images &&
                    images.length === 0 &&
                    (deviceAccess === AccessLevel.ADMIN ||
                        deviceAccess === AccessLevel.OWNER) && (
                        <div>No images found for this date/hour.</div>
                    )}
                <Stack
                    sx={{ width: '100%', height: 'calc(100dvh - 200px)' }}
                    direction="row"
                    spacing={2}
                >
                    <GpsTrack
                        gpsTrack={gpsTrack || []}
                        currentTrack={data?.gps || []}
                    />
                    <Stack
                        sx={{
                            width: 'calc(100% - 400px)',
                            height: '100%',
                            overflowY: 'auto',
                            pr: 1,
                            justifyContent: 'flex-start',
                            alignItems: 'flex-start',
                        }}
                    >
                        {segments.map((segment, index) => (
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
                        ))}
                        {data && data.total_pages > 1 && (
                            <Pagination
                                page={page}
                                count={data?.total_pages || 1}
                                color="primary"
                                onChange={(_, page) => {
                                    setPage(page);
                                    const element =
                                        document.getElementById('app');
                                    element?.scrollIntoView({
                                        behavior: 'smooth',
                                    });
                                }}
                            />
                        )}
                    </Stack>
                </Stack>
            </Stack>
            <ImageZoom onDelete={() => mutate()} />
        </>
    );
}

export default MainPage;

import {
    Button,
    Container,
    Pagination,
    Stack,
    Typography,
} from '@mui/material';
import CustomDatePicker from 'components/CustomDatePicker';
import DaySummaryComponent from 'components/DaySummary';
import LifelogEvent from 'components/LifelogEvent';
import React, { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { setDeviceId } from 'reducers/auth';
import { setLoading } from 'reducers/feedback';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import useSWR from 'swr';
import { AccessLevel } from 'types/auth';
import { deleteImage, getAllDates, getImagesByHour } from '../apis/browsing';
import '../App.css';
import { ImageZoom } from '../components/ImageZoom';
import DeviceSelect from './DeviceSelect';
import GoalConfig from 'components/GoalConfig';
import DeleteRange from 'components/DeleteRange';

function MainPage() {
    const navigate = useNavigate();
    const [searchParams, _] = useSearchParams();
    const date = searchParams.get('date');
    const device = searchParams.get('device_id');
    const deviceId = useAppSelector((state) => state.auth.deviceId);

    const { deviceAccess } = useAppSelector((state) => state.auth);
    const [page, setPage] = React.useState(1);
    const [hour, setHour] = React.useState<number | null>(null);

    useEffect(() => {
        if (device) dispatch(setDeviceId(device));
    }, [device]);

    const dispatch = useAppDispatch();
    const { data, mutate } = useSWR(
        [page, date, hour, deviceId, deviceAccess],
        async () => {
            if (
                deviceAccess === AccessLevel.ADMIN ||
                deviceAccess === AccessLevel.OWNER
            ) {
                setHour(hour || 0);
                return await getImagesByHour(
                    deviceId,
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
                };
            }
        },
        {
            revalidateOnFocus: false,
        }
    );

    const { data: allDates } = useSWR(
        ['all-dates', deviceId, date],
        async () => {
            const allDates = await getAllDates(deviceId);
            return allDates;
        },
        {
            revalidateOnFocus: false,
        }
    );

    const images = data?.images;
    const segments = data?.segments || [];
    const availableHours = data?.available_hours || [];

    useEffect(() => {
        setPage(1);
    }, [date, deviceId]);

    useEffect(() => {
        if (availableHours.length > 0 && !availableHours.includes(hour || 0)) {
            setHour(availableHours[0]);
        }
    }, [data, availableHours, hour]);

    const deleteRow = (imagePaths: string[]) => {
        dispatch(setLoading(true));
        Promise.all(imagePaths.map((path) => deleteImage(deviceId, path))).then(
            () => {
                mutate().then(() => dispatch(setLoading(false)));
            }
        );
    };

    return (
        <>
            <Stack spacing={2} alignItems="center" sx={{ padding: 2 }} id="app">
                <Container>
                    <Stack
                        direction="row"
                        spacing={2}
                        width="100%"
                        pl={1}
                        alignItems="center"
                        mb={2}
                    >
                        <DeviceSelect
                            onChange={(device: string) => {
                                navigate(
                                    `/?date=${date || ''}${
                                        device ? `&device_id=${device}` : ''
                                    }`
                                );
                            }}
                        />
                        <CustomDatePicker
                            date={date}
                            setPage={setPage}
                            setHour={setHour}
                            allDates={allDates}
                        />
                    </Stack>
                    {/* <Settings /> */}
                    <DaySummaryComponent />
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
                    sx={{ width: '100%', flexWrap: 'wrap', pb: 2 }}
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
                <DeleteRange onDelete={() => mutate()} date={date || ''} />
                {segments.length === 0 &&
                    images &&
                    images.length === 0 &&
                    (deviceAccess === AccessLevel.ADMIN ||
                        deviceAccess === AccessLevel.OWNER) && (
                        <div>No images found for this date/hour.</div>
                    )}
                <Stack spacing={2} sx={{ width: '100%' }}>
                    {segments.map((segment, index) => (
                        <LifelogEvent
                            key={index}
                            segment={segment}
                            onChange={() => {
                                dispatch(setLoading(true));
                                mutate().then(() =>
                                    dispatch(setLoading(false))
                                );
                            }}
                            deleteRow={deleteRow}
                        />
                    ))}
                </Stack>
                {data && data.total_pages > 1 && (
                    <Pagination
                        page={page}
                        count={data?.total_pages || 1}
                        color="primary"
                        onChange={(_, page) => {
                            setPage(page);
                            const element = document.getElementById('app');
                            element?.scrollIntoView({ behavior: 'smooth' });
                        }}
                    />
                )}
            </Stack>
            <ImageZoom onDelete={() => mutate()} />
        </>
    );
}

export default MainPage;

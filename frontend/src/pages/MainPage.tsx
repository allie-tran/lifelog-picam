import {
    AdminPanelSettingsRounded,
    RotateLeftRounded,
    SearchRounded,
    UploadRounded,
} from '@mui/icons-material';
import {
    Badge,
    Box,
    Button,
    Divider,
    Drawer,
    IconButton,
    Pagination,
    Stack,
    TextField,
    Typography,
} from '@mui/material';
import { PickersDay, PickersDayProps } from '@mui/x-date-pickers';
import { DatePicker } from '@mui/x-date-pickers/DatePicker';
import { ImageObject } from '@utils/types';
import { changeSegmentActivity } from 'apis/process';
import DaySummaryComponent from 'components/DaySummary';
import ModalWithCloseButton from 'components/ModalWithCloseButton';
import dayjs from 'dayjs';
import React, { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { setLoading } from 'reducers/feedback';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import { setZoomedImage } from 'reducers/zoomedImage';
import useSWR from 'swr';
import { AccessLevel } from 'types/auth';
import { deleteImage, getAllDates, getImagesByHour } from '../apis/browsing';
import '../App.css';
import DeletedImages from '../components/DeletedImages';
import ImageWithDate from '../components/ImageWithDate';
import { ImageZoom } from '../components/ImageZoom';
import Settings from '../components/Settings';
import DeviceSelect from './DeviceSelect';
import { setDeviceId } from 'reducers/auth';
import { CONFIDENCE_COLOURS } from 'constants/activityColors';

const AvailableDay = (props: PickersDayProps & { allDates: string[] }) => {
    const { allDates = [], day, outsideCurrentMonth, ...other } = props;
    if (!allDates.includes(day.format('YYYY-MM-DD'))) {
        return (
            <PickersDay
                {...other}
                day={day}
                outsideCurrentMonth={outsideCurrentMonth}
            />
        );
    }

    return (
        <Badge key={day.toString()} variant="dot" color="primary">
            <PickersDay
                {...other}
                day={day}
                outsideCurrentMonth={outsideCurrentMonth}
            />
        </Badge>
    );
};


function MainPage() {
    const navigate = useNavigate();
    const [searchParams, _] = useSearchParams();
    const date = searchParams.get('date');
    const device = searchParams.get('device_id');
    const deviceId = useAppSelector((state) => state.auth.deviceId);

    const { deviceAccess } = useAppSelector((state) => state.auth);
    const [page, setPage] = React.useState(1);
    const [hour, setHour] = React.useState<number | null>(null);
    const [segmentToEdit, setSegmentToEdit] = React.useState<number | null>(
        null
    );
    const [activityEditText, setActivityEditText] = React.useState<string>('');

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
            if (!date || !allDates.includes(date)) {
                // go to the latest date with images
                const latestDate: string = allDates[allDates.length - 1];
                if (!latestDate) return allDates;
                navigate(
                    `/?date=${latestDate}${deviceId ? `&device_id=${deviceId}` : ''}`
                );
            }
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
                <Divider flexItem />
                <DeviceSelect
                    onChange={(device: string) => {
                        navigate(
                            `/?date=${date || ''}${
                                device ? `&device_id=${device}` : ''
                            }`
                        );
                    }}
                />
                <Drawer
                    variant="permanent"
                    open
                    sx={{ zIndex: (theme) => theme.zIndex.appBar - 1 }}
                >
                    <Box sx={{ height: '48px' }} />
                    <DeletedImages />
                    <IconButton
                        color="secondary"
                        onClick={() => navigate('/search')}
                        sx={{ marginTop: '16px', marginLeft: '8px' }}
                    >
                        <SearchRounded />
                    </IconButton>
                    <IconButton
                        color="secondary"
                        onClick={() => navigate('/admin')}
                        sx={{ marginTop: '16px', marginLeft: '8px' }}
                    >
                        <AdminPanelSettingsRounded />
                    </IconButton>
                    <IconButton
                        color="secondary"
                        onClick={() => navigate('/upload')}
                        sx={{ marginTop: '16px', marginLeft: '8px' }}
                    >
                        <UploadRounded />
                    </IconButton>
                    <IconButton
                        color="secondary"
                        onClick={() => navigate('/status')}
                        sx={{ marginTop: '16px', marginLeft: '8px' }}
                    >
                        <RotateLeftRounded />
                    </IconButton>
                </Drawer>
                <Typography variant="h4" color="primary" fontWeight="bold">
                    {data?.date || 'All Dates'}
                </Typography>
                <DatePicker
                    label="Select Date"
                    value={date ? dayjs(date) : null}
                    onChange={(newValue) => {
                        setPage(1);
                        setHour(null);
                        navigate(
                            `/?date=${newValue?.format('YYYY-MM-DD') || ''}`
                        );
                    }}
                    slots={{
                        day: (props) => (
                            <AvailableDay
                                {...props}
                                allDates={allDates || []}
                            />
                        ),
                    }}
                />
                <Settings />
                <DaySummaryComponent />
                <Stack
                    direction="row"
                    spacing={1}
                    sx={{ width: '100%', flexWrap: 'wrap' }}
                    useFlexGap
                    justifyContent="center"
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
                {segments.length === 0 &&
                    images &&
                    images.length === 0 &&
                    (deviceAccess === AccessLevel.ADMIN ||
                        deviceAccess === AccessLevel.OWNER) && (
                        <div>No images found for this date/hour.</div>
                    )}
                <Stack spacing={2} sx={{ width: '100%' }}>
                    {segments.map((segment, index) => {
                        const firstImage = segment[0];

                        return (
                            <React.Fragment key={index}>
                                <Typography
                                    variant="h6"
                                    fontWeight="bold"
                                    color={
                                        CONFIDENCE_COLOURS[
                                            firstImage.activityConfidence ||
                                                'Low'
                                        ]
                                    }
                                >
                                    {firstImage.activity
                                        ? `${firstImage.activity} (Confidence: ${firstImage.activityConfidence})`
                                        : 'No Activity Detected'}
                                </Typography>
                                <Typography>
                                    {firstImage.activityDescription}
                                </Typography>
                                <Stack
                                    direction="row"
                                    spacing={2}
                                    key={index}
                                    sx={{
                                        maxWidth: '100vw',
                                        overflowY: 'auto',
                                        height: '400px',
                                    }}
                                >
                                    {segment.map((image: ImageObject) => (
                                        <ImageWithDate
                                            image={image}
                                            onClick={() => {
                                                console.log(
                                                    'Setting zoomed image:',
                                                    image.imagePath
                                                );
                                                dispatch(
                                                    setZoomedImage({
                                                        image: image.imagePath,
                                                        isVideo: image.isVideo,
                                                    })
                                                );
                                            }}
                                            onDelete={() => mutate()}
                                        />
                                    ))}
                                </Stack>
                                <Button
                                    color="error"
                                    onClick={() => {
                                        const imagePaths = segment.map(
                                            (img) => img.imagePath
                                        );
                                        deleteRow(imagePaths);
                                    }}
                                >
                                    Delete All {segment.length} Images in this
                                    Row
                                </Button>
                                {firstImage.segmentId ? (
                                    <Button
                                        variant="outlined"
                                        onClick={() => {
                                            setSegmentToEdit(
                                                firstImage.segmentId as unknown as number
                                            );
                                            setActivityEditText(
                                                firstImage.activity || ''
                                            );
                                        }}
                                    >
                                        Edit Activity Info
                                    </Button>
                                ) : null}
                                <Divider flexItem />
                            </React.Fragment>
                        );
                    })}
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
            <ModalWithCloseButton
                open={segmentToEdit !== null}
                onClose={() => setSegmentToEdit(null)}
            >
                <Stack spacing={2} sx={{ padding: 2, width: '400px' }}>
                    <Typography>
                        Edit activity for segment #
                        {segmentToEdit !== null ? segmentToEdit + 1 : ''}
                    </Typography>
                    <TextField
                        label="New Activity Info"
                        multiline
                        minRows={3}
                        value={activityEditText}
                        onChange={(e) => setActivityEditText(e.target.value)}
                    />
                    <Button
                        variant="contained"
                        onClick={() => {
                            dispatch(setLoading(true));
                            changeSegmentActivity(
                                deviceId,
                                segmentToEdit as unknown as number,
                                activityEditText
                            ).then(() => {
                                mutate();
                                setSegmentToEdit(null);
                                dispatch(setLoading(false));
                            });
                        }}
                    >
                        Save Changes
                    </Button>
                </Stack>
            </ModalWithCloseButton>
        </>
    );
}

export default MainPage;

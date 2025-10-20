import {
    Badge,
    Box,
    Button,
    Drawer,
    IconButton,
    Pagination,
    Paper,
    Stack,
    Toolbar,
    Typography,
} from '@mui/material';
import { PickersDay, PickersDayProps } from '@mui/x-date-pickers';
import { DatePicker } from '@mui/x-date-pickers/DatePicker';
import { ImageObject } from '@utils/types';
import DaySummary from 'components/DaySummary';
import dayjs from 'dayjs';
import React from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { useAppDispatch } from 'reducers/hooks';
import { setZoomedImage } from 'reducers/zoomedImage';
import useSWR from 'swr';
import { deleteImage, getAllDates, getImagesByHour } from '../apis/browsing';
import '../App.css';
import DeletedImages from '../components/DeletedImages';
import ImageWithDate from '../components/ImageWithDate';
import { ImageZoom } from '../components/ImageZoom';
import SearchBar from '../components/SearchBar';
import Settings from '../components/Settings';
import { SearchRounded } from '@mui/icons-material';

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

    const [page, setPage] = React.useState(1);
    const [hour, setHour] = React.useState<number | null>(null);
    const dispatch = useAppDispatch();
    const { data, error, mutate } = useSWR(
        [page, date, hour],
        () => getImagesByHour(date || '', hour || 0, page),
        {
            revalidateOnFocus: false,
        }
    );

    const { data: allDates } = useSWR('all-dates', getAllDates, {
        revalidateOnFocus: false,
    });

    const images = data?.images;
    const segments = data?.segments || [];
    const availableHours = data?.available_hours || [];

    const deleteRow = (imagePaths: string[]) => {
        Promise.all(imagePaths.map((path) => deleteImage(path))).then(() =>
            mutate()
        );
    };

    return (
        <>
            <Stack spacing={2} alignItems="center" sx={{ padding: 2 }} id="app">
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
                <DaySummary />
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
                {error && <div>Failed to load images</div>}
                {segments.length === 0 && images && images.length === 0 && (
                    <div>No images found for this date/hour.</div>
                )}
                <Stack spacing={2} sx={{ width: '100%' }}>
                    {segments.map((segment, index) => (
                        <React.Fragment key={index}>
                            <Button
                                color="error"
                                onClick={() => {
                                    const imagePaths = segment.map(
                                        (img) => img.imagePath
                                    );
                                    deleteRow(imagePaths);
                                }}
                            >
                                Delete All {segment.length} Images in this Row
                            </Button>
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
                        </React.Fragment>
                    ))}
                </Stack>
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
            </Stack>
            <ImageZoom onDelete={() => mutate()} />
        </>
    );
}
export default MainPage;

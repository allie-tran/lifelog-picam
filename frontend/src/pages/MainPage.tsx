import { Badge, Button, Pagination, Stack, Typography } from '@mui/material';
import { PickersDay, PickersDayProps } from '@mui/x-date-pickers';
import { DatePicker } from '@mui/x-date-pickers/DatePicker';
import dayjs, { Dayjs } from 'dayjs';
import React from 'react';
import useSWR from 'swr';
import '../App.css';
import { DeleteRounded } from '@mui/icons-material';
import SearchInterface from '../components/SearchInterface';
import DeletedImages from '../components/DeletedImages';
import { ImageObject } from '../types/types';
import ImageWithDate from '../components/ImageWithDate';
import { ImageZoom } from '../components/ImageZoom';
import { deleteImage, getAllDates, getImagesByHour } from '../apis/browsing';
import Settings from '../components/Settings';
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
    const [page, setPage] = React.useState(1);
    const [date, setDate] = React.useState<Dayjs | null>(dayjs());
    const [hour, setHour] = React.useState<number | null>(null);
    const [selectedImage, setSelectedImage] = React.useState<string | null>(
        null
    );
    const [isSelectedVideo, setIsSelectedVideo] = React.useState<boolean>(false);
    const { data, error, mutate } = useSWR(
        [page, date, hour],
        () =>
            getImagesByHour(
                date ? date.format('YYYY-MM-DD') : '',
                hour || 0,
                page
            ),
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
                <Typography variant="h4" color="primary" fontWeight="bold">
                    {data?.date || 'All Dates'}
                </Typography>
                <DatePicker
                    label="Select Date"
                    value={date}
                    onChange={(newValue) => {
                        setDate(newValue);
                        setPage(1);
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
                <SearchInterface />
                <DeletedImages />
                <Stack direction="row" spacing={1}>
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
                {!images && !error && <div>Loading...</div>}
                {segments.length === 0 && images && images.length === 0 && (
                    <div>No images found for this date/hour.</div>
                )}
                <Stack>
                    {segments.map((segment, index) => (
                        <React.Fragment key={index}>
                            <Button
                                color="error"
                                onClick={() => {
                                    const imagePaths = segment.map(
                                        (img) => img.image_path
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
                                        key={image.image_path}
                                        imagePath={image.image_path}
                                        timestamp={image.timestamp}
                                        onClick={() => {
                                            setSelectedImage(image.image_path)
                                            setIsSelectedVideo(image.is_video)
                                        }}
                                        extra={
                                            <Button
                                                color="error"
                                                size="small"
                                                onClick={() =>
                                                    deleteImage(
                                                        image.image_path
                                                    ).then(() => mutate())
                                                }
                                            >
                                                <DeleteRounded />
                                            </Button>
                                        }
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
            {selectedImage && (
                <ImageZoom
                    imagePath={selectedImage}
                    onClose={() => setSelectedImage(null)}
                    onDelete={() => mutate()}
                    isVideo={isSelectedVideo}
                />
            )}
        </>
    );
}
export default MainPage;

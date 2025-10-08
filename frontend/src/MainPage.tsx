import { Badge, Button, Pagination, Stack, Typography } from '@mui/material';
import { PickersDay, PickersDayProps } from '@mui/x-date-pickers';
import { DatePicker } from '@mui/x-date-pickers/DatePicker';
import dayjs, { Dayjs } from 'dayjs';
import React from 'react';
import useSWR from 'swr';
import './App.css';
import { IMAGE_HOST_URL } from './constants';
import { deleteImage, getAllDates, getImages, getImagesByHour } from './events';
import ImageWithDate from './ImageWithDate';
import { ImageZoom } from './ImageZoom';
import SearchInterface from './SearchInterface';
import { ImageObject } from './types';
import DeletedImages from './DeletedImages';
import { DeleteRounded } from '@mui/icons-material';
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
    const { data, error, mutate } = useSWR(
        [page, date, hour],
        () => getImagesByHour(date ? date.format('YYYY-MM-DD') : "", hour || 0),
        {
            revalidateOnFocus: false,
        }
    );

    const { data: allDates } = useSWR('all-dates', getAllDates, {
        revalidateOnFocus: false,
    });

    const images = data?.images;
    const availableHours = data?.available_hours || [];

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
                {images && (
                    <div className="image-grid">
                        {images.map((image: ImageObject) => (
                            <ImageWithDate
                                key={image.image_path}
                                imagePath={image.image_path}
                                timestamp={image.timestamp}
                                onClick={() =>
                                    setSelectedImage(image.image_path)
                                }
                                extra={
                                    <Button
                                        color="error"
                                        size="small"
                                        onClick={() =>
                                            deleteImage(image.image_path).then(
                                                () => mutate()
                                            )
                                        }
                                    >
                                        <DeleteRounded />
                                    </Button>
                                }
                            />
                        ))}
                    </div>
                )}
                <Pagination
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
                />
            )}
        </>
    );
}
export default MainPage;

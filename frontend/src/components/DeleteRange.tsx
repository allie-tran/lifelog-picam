import { deleteImages, getImagesByRange } from 'apis/browsing';
import { Button, Stack, Typography } from '@mui/material';
import { TimePicker } from '@mui/x-date-pickers';
import { ImageObject } from '@utils/types';
import dayjs, { Dayjs } from 'dayjs';
import React from 'react';
import ModalWithCloseButton from './ModalWithCloseButton';
import { useAppSelector } from 'reducers/hooks';
import ImageWithDate from './ImageWithDate';
import { DeleteRounded } from '@mui/icons-material';

const DeleteRange = ({
    onDelete,
    date,
}: {
    onDelete: () => void;
    date: string;
}) => {
    const deviceId = useAppSelector((state) => state.auth.deviceId);
    const [open, setOpen] = React.useState(false);
    const [startTime, setStartTime] = React.useState<Dayjs | null>(
        dayjs().subtract(5, 'minute')
    );
    const [endTime, setEndTime] = React.useState<Dayjs | null>(dayjs());
    const [images, setImages] = React.useState<ImageObject[]>([]);

    const handlePreview = async () => {
        if (startTime && endTime) {
            let startTimeWithDate = dayjs(date)
            startTimeWithDate = startTimeWithDate.hour(startTime.hour()).minute(startTime.minute()).second(startTime.second());
            let endTimeWithDate = dayjs(date)
            endTimeWithDate = endTimeWithDate.hour(endTime.hour()).minute(endTime.minute()).second(endTime.second());

            const images = await getImagesByRange(
                deviceId,
                date,
                startTimeWithDate.valueOf(),
                endTimeWithDate.valueOf()
            );
            setImages(images);
        }
    };

    const handleDelete = async () => {
        deleteImages(
            deviceId,
            images.map((img) => img.imagePath)
        );
        onDelete();
        setOpen(false);
    };

    return (
        <>
            <Button
                color="secondary"
                onClick={() => setOpen(true)}
            >
                <DeleteRounded sx={{ mr: 1 }} />
                Delete Last 5 Minutes
            </Button>
            <ModalWithCloseButton open={open} onClose={() => setOpen(false)}>
                <Stack spacing={2} sx={{ p: 3 }}>
                    <Typography variant="body1" gutterBottom>
                        This will delete all images captured between the
                        specified start and end times.
                    </Typography>
                    <TimePicker
                        label="Start Time"
                        value={startTime}
                        onChange={(newValue) => setStartTime(newValue)}
                    />
                    <TimePicker
                        label="End Time"
                        value={endTime}
                        onChange={(newValue) => setEndTime(newValue)}
                        sx={{ mt: 2 }}
                    />
                    <Button
                        color="secondary"
                        onClick={handlePreview}
                        disabled={!startTime || !endTime}
                        sx={{ mt: 2 }}
                    >
                        Preview
                    </Button>
                    {images.length > 0 && (
                        <Button
                            color="error"
                            variant="contained"
                            onClick={handleDelete}
                            disabled={!startTime || !endTime}
                            sx={{ mt: 2 }}
                        >
                            Confirm Delete
                        </Button>
                    )}
                </Stack>
                <Stack
                    spacing={1}
                    direction="row"
                    useFlexGap
                    flexWrap="wrap"
                    sx={{ p: 3 }}
                >
                    {images.map((img) => (
                        <ImageWithDate image={img} />
                    ))}
                </Stack>
            </ModalWithCloseButton>
        </>
    );
};

export default DeleteRange;

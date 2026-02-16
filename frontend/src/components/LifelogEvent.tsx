import { Button, Divider, Stack, TextField, Typography } from '@mui/material';
import { ImageObject } from '@utils/types';
import { changeSegmentActivity } from 'apis/process';
import ModalWithCloseButton from 'components/ModalWithCloseButton';
import { CONFIDENCE_COLOURS } from 'constants/activityColors';
import dayjs from 'dayjs';
import React from 'react';
import { setLoading } from 'reducers/feedback';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import { setZoomedImage } from 'reducers/zoomedImage';
import '../App.css';
import ImageWithDate from '../components/ImageWithDate';

const LifelogEvent = ({
    segment,
    onChange,
    deleteRow,
    fullTime = false,
}: {
    segment: ImageObject[];
    onChange: () => void;
    deleteRow: (imagePaths: string[]) => void;
    fullTime?: boolean;
}) => {
    const dispatch = useAppDispatch();
    const deviceId = useAppSelector((state) => state.auth.deviceId);
    const firstImage = segment[0];
    const lastImage = segment[segment.length - 1];
    const count = segment.length;
    const [edit, setEdit] = React.useState(false);
    const [activityEditText, setActivityEditText] = React.useState('');
    const color = CONFIDENCE_COLOURS[firstImage?.activityConfidence || 0];


    return (
        <React.Fragment>
            <Stack
                spacing={1}
                sx={{
                    flex: count < 3 ? '1 0 500px' : '1 0 100%',
                    maxWidth: '100%',
                    justifyContent: 'space-between',
                }}
            >
                <Stack
                    direction="row"
                    justifyContent="space-between"
                    alignItems="center"
                >
                    <Stack direction="row" spacing={1} flexShrink={0} alignItems="center">
                        <Typography variant="subtitle1" fontWeight="bold">
                            {firstImage.activity
                                ? `${firstImage.activity}`
                                : 'No Activity Detected'}
                        </Typography>
                        {firstImage.activityConfidence && (
                            <Typography
                                variant="subtitle2"
                                color={color || 'textSecondary'}
                            >
                                Confidence: {firstImage.activityConfidence}
                            </Typography>
                        )}
                    </Stack>
                    <Typography
                        variant="subtitle2"
                        color="textSecondary"
                        textAlign="right"
                        sx={{ flexShrink: 0, minWidth: 300 }}
                    >
                        {dayjs(lastImage.timestamp).format('HH:mm:ss')} -{' '}
                        {dayjs(firstImage.timestamp).format('HH:mm:ss')}{' '}
                        {fullTime && (
                            <strong>{dayjs(firstImage.timestamp).format('ll')}</strong>
                        )}
                    </Typography>
                </Stack>
                <Typography>{firstImage.activityDescription}</Typography>
                <Stack direction="row" spacing={2} alignItems="center">
                    {firstImage.segmentId ? (
                        <Button
                            color="primary"
                            onClick={() => {
                                setEdit(true);
                                setActivityEditText(firstImage.activity || '');
                            }}
                            sx={{
                                textDecoration: 'underline',
                                textTransform: 'none',
                                p: 0,
                            }}
                        >
                            Edit Activity Info
                        </Button>
                    ) : null}
                    <Button
                        color="error"
                        onClick={() => {
                            const imagePaths = segment.map(
                                (img) => img.imagePath
                            );
                            deleteRow(imagePaths);
                        }}
                        sx={{
                            textDecoration: 'underline',
                            textTransform: 'none',
                            p: 0,
                        }}
                    >
                        Delete Row
                    </Button>
                </Stack>
                <Stack
                    direction="row"
                    spacing={2}
                    sx={{
                        maxWidth: '100vw',
                        overflowY: 'auto',
                        height: '300px',
                        p: 0,
                    }}
                >
                    {segment.map((image: ImageObject) => (
                        <ImageWithDate
                            timeOnly
                            height={'250px'}
                            image={image}
                            onClick={() => {
                                dispatch(
                                    setZoomedImage({
                                        image: image.imagePath,
                                        isVideo: image.isVideo,
                                    })
                                );
                            }}
                            onDelete={onChange}
                        />
                    ))}
                </Stack>
            </Stack>
            <ModalWithCloseButton open={edit} onClose={() => setEdit(false)}>
                <Stack spacing={2} sx={{ padding: 2, width: '400px' }}>
                    <Typography>
                        Edit activity for segment #{firstImage.segmentId}
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
                                firstImage.segmentId as unknown as number,
                                activityEditText
                            ).then(() => {
                                onChange();
                                dispatch(setLoading(false));
                                setEdit(false);
                            });
                        }}
                    >
                        Save Changes
                    </Button>
                </Stack>
            </ModalWithCloseButton>
        </React.Fragment>
    );
};

export default LifelogEvent;

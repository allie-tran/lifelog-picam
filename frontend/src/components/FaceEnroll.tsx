import {
    CameraAltRounded,
    FaceRounded,
    RefreshRounded,
} from '@mui/icons-material';
import {
    Box,
    Button,
    Chip,
    Paper,
    Stack,
    TextField,
    Typography,
} from '@mui/material';
import { ImageObject } from '@utils/types';
import { addToWhiteList, getFaces } from 'apis/browsing';
import { useState } from 'react';
import Webcam from 'react-webcam';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import useFaceEnrollmentWithPose from './useFaceEnrollmentWithPose';
import ImageWithDate from './ImageWithDate';
import { showNotification } from 'reducers/feedback';

const videoConstraints = {
    width: 720,
    height: 360,
    facingMode: 'user',
};

const FaceEnroll = ({ onUpdate }: { onUpdate: () => void }) => {
    const dispatch = useAppDispatch();
    const { webcamRef, status, capturedImages, startEnrollment, done } =
        useFaceEnrollmentWithPose();

    const deviceId = useAppSelector((state) => state.auth.deviceId) || '';
    const [enabled, setEnabled] = useState<boolean>(false);
    const [images, setImages] = useState<ImageObject[]>([]);
    const [name, setName] = useState<string>('');
    const [open, setOpen] = useState<boolean>(false);

    const handleAddToWhiteList = () => {
        addToWhiteList(deviceId, capturedImages, name)
            .then(() => {
                dispatch(
                    showNotification({
                        message: 'Face added to white list successfully!',
                        type: 'success',
                    })
                );
                setEnabled(false);
                setImages([]);
                onUpdate();
            })
            .catch((err) => {
                console.error('Error adding face to white list:', err);
                dispatch(
                    showNotification({
                        message:
                            'Failed to add face to white list. Please try again.',
                        type: 'error',
                    })
                );
            });
    };

    const handleGetFaces = () => {
        getFaces(deviceId, capturedImages)
            .then((faces) => {
                setImages(faces);
            })
            .catch((err) => {
                console.error('Error fetching faces:', err);
                dispatch(
                    showNotification({
                        message: 'Failed to fetch faces. Please try again.',
                        type: 'error',
                    })
                );
            });
    };

    return (
        <>
            {open ? (
                <>
                    <Typography variant="h6" gutterBottom>
                        Add Recognized Face to White List
                    </Typography>
                    <TextField
                        label="Name"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        margin="normal"
                    />
                    <Button
                        variant="contained"
                        color="primary"
                        onClick={handleAddToWhiteList}
                        disabled={!name.trim()}
                    >
                        Add
                    </Button>
                </>
            ) : (
                <>
                    <Stack direction="row" spacing={4} alignItems="flex-start">
                        <Paper elevation={3} sx={{ p: 2 }}>
                            {!enabled ? (
                                <Stack spacing={2}>
                                    <Stack
                                        direction="row"
                                        alignItems="center"
                                        justifyContent="space-between"
                                        sx={{
                                            position: 'relative',
                                            width: '100%',
                                        }}
                                    >
                                        <Typography
                                            variant="subtitle1"
                                            fontWeight="bold"
                                        >
                                            Live Camera Feed
                                        </Typography>
                                        <Chip
                                            color="success"
                                            label="Inactive"
                                            size="small"
                                        />
                                    </Stack>
                                    <Box
                                        sx={{
                                            width: '400px',
                                            height: '300px',
                                            backgroundColor: '#1e1e1e',
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'center',
                                            borderRadius: 1,
                                        }}
                                    >
                                        <Button
                                            color="primary"
                                            onClick={() => setEnabled(true)}
                                        >
                                            <CameraAltRounded sx={{ mr: 1 }} />
                                            Enable Camera
                                        </Button>
                                    </Box>
                                </Stack>
                            ) : done ? (
                                <Stack spacing={2}>
                                    <Stack
                                        direction="row"
                                        alignItems="center"
                                        justifyContent="space-between"
                                        sx={{
                                            position: 'relative',
                                            width: '100%',
                                        }}
                                    >
                                        <Typography
                                            variant="subtitle1"
                                            fontWeight="bold"
                                        >
                                            Captured Images
                                        </Typography>
                                        <Chip
                                            color="success"
                                            label="Captured"
                                            size="small"
                                        />
                                    </Stack>
                                    <Stack
                                        direction="row"
                                        spacing={2}
                                        flexWrap="wrap"
                                        useFlexGap
                                    >
                                        {capturedImages.map(
                                            (image: string, index: number) => (
                                                <img
                                                    key={`captured-image-${index}`}
                                                    src={image}
                                                    alt={`Captured ${index + 1}`}
                                                    style={{
                                                        maxWidth: '200px',
                                                        borderRadius: '8px',
                                                    }}
                                                />
                                            )
                                        )}
                                    </Stack>
                                    <Stack direction="row" spacing={2}>
                                        <Button
                                            color="error"
                                            onClick={startEnrollment}
                                        >
                                            <RefreshRounded sx={{ mr: 1 }} />
                                            Retry
                                        </Button>
                                        <Button
                                            variant="outlined"
                                            color="primary"
                                            onClick={handleGetFaces}
                                            sx={{ mt: 2 }}
                                        >
                                            <FaceRounded sx={{ mr: 1 }} />
                                            Recognize Faces
                                        </Button>
                                        {images.length > 0 && (
                                            <Button
                                                variant="contained"
                                                onClick={() => setOpen(true)}
                                                sx={{ mt: 2 }}
                                            >
                                                Add to White List
                                            </Button>
                                        )}
                                    </Stack>
                                </Stack>
                            ) : (
                                <Stack spacing={2} width="400px">
                                    <Stack
                                        direction="row"
                                        alignItems="center"
                                        justifyContent="space-between"
                                        sx={{
                                            position: 'relative',
                                            width: '100%',
                                        }}
                                    >
                                        <Typography
                                            variant="subtitle1"
                                            fontWeight="bold"
                                        >
                                            Live Camera Feed
                                        </Typography>
                                        <Chip
                                            color="success"
                                            label="Live"
                                            size="small"
                                        />
                                    </Stack>
                                    <Webcam
                                        mirrored
                                        screenshotFormat="image/jpeg"
                                        ref={webcamRef}
                                        videoConstraints={videoConstraints}
                                    ></Webcam>
                                    <Typography
                                        variant="body2"
                                        color="textSecondary"
                                        align="center"
                                    >
                                        {status}
                                    </Typography>
                                    {status === 'Ready for Enrollment' && (
                                        <Button
                                            variant="contained"
                                            color="primary"
                                            onClick={startEnrollment}
                                        >
                                            Start Enrollment
                                        </Button>
                                    )}
                                </Stack>
                            )}
                        </Paper>
                    </Stack>
                    {images.length > 0 && (
                        <Stack spacing={2} sx={{ mt: 4 }}>
                            <Typography variant="h6">
                                Recognized Faces in the past 30 minutes
                            </Typography>
                            <Stack
                                direction="row"
                                spacing={2}
                                flexWrap="wrap"
                                useFlexGap
                            >
                                {images.map((image, index) => (
                                    <ImageWithDate
                                        image={image}
                                        key={`recognized-face-${index}`}
                                    />
                                ))}
                            </Stack>
                        </Stack>
                    )}
                </>
            )}
        </>
    );
};

export default FaceEnroll;

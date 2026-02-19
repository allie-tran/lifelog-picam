import { addToWhiteList, getFaces } from 'apis/browsing';
import {
    Box,
    Button,
    Chip,
    Paper,
    Stack,
    TextField,
    Typography,
} from '@mui/material';
import { useCallback, useRef, useState } from 'react';
import Webcam from 'react-webcam';
import { useAppSelector } from 'reducers/hooks';
import { ImageObject } from '@utils/types';
import ImageWithDate from './ImageWithDate';
import {
    CameraAltRounded,
    CameraRounded,
    FaceRounded,
    RefreshRounded,
} from '@mui/icons-material';
import ModalWithCloseButton from './ModalWithCloseButton';

const videoConstraints = {
    width: 720,
    height: 360,
    facingMode: 'user',
};

const FaceEnroll = ({ onUpdate }: { onUpdate: () => void }) => {
    const webcamRef = useRef<Webcam>(null);
    const deviceId = useAppSelector((state) => state.auth.deviceId) || '';
    const [enabled, setEnabled] = useState<boolean>(false);
    const [images, setImages] = useState<ImageObject[]>([]);
    const [url, setUrl] = useState<string>('');
    const [name, setName] = useState<string>('');
    const [open, setOpen] = useState<boolean>(false);
    const capture = useCallback(() => {
        if (webcamRef.current) {
            const imageSrc = webcamRef.current.getScreenshot();
            if (imageSrc) {
                console.log('Captured image:', imageSrc);
                setUrl(imageSrc);
            }
        }
    }, [webcamRef]);

    const handleAddToWhiteList = () => {
        addToWhiteList(deviceId, url, name)
            .then(() => {
                alert('Face added to white list successfully!');
                setUrl('');
                setEnabled(false);
                setImages([]);
                onUpdate();
            })
            .catch((err) => {
                console.error('Error adding face to white list:', err);
                alert('Failed to add face to white list. Please try again.');
            });
    };

    const handleGetFaces = () => {
        getFaces(deviceId, url)
            .then((faces) => {
                setImages(faces);
            })
            .catch((err) => {
                console.error('Error fetching faces:', err);
                alert('Failed to fetch faces. Please try again.');
            });
    };

    return (
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
                    ) : url ? (
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
                                    Captured Image
                                </Typography>
                                <Chip
                                    color="success"
                                    label="Captured"
                                    size="small"
                                />
                            </Stack>
                            <img
                                src={url}
                                alt="Captured"
                                style={{ maxWidth: '100%' }}
                            />
                            <Stack direction="row" spacing={2}>
                                <Button
                                    color="error"
                                    onClick={() => {
                                        setUrl('');
                                        setImages([]);
                                    }}
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
                            <Button
                                variant="contained"
                                color="primary"
                                onClick={capture}
                            >
                                Capture
                            </Button>
                        </Stack>
                    )}
                </Paper>
            </Stack>
            {images.length > 0 && (
                <Stack spacing={2}>
                    <Typography variant="h6">Recognized Faces:</Typography>
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
            <ModalWithCloseButton open={open} onClose={() => setOpen(false)}>
                <Typography variant="h6" gutterBottom>
                    Add Recognized Face to White List
                </Typography>
                <TextField
                    label="Name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    fullWidth
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
            </ModalWithCloseButton>
        </>
    );
};

export default FaceEnroll;

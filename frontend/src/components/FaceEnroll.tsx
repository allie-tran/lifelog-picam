import { CameraAltRounded, DeleteRounded, PhotoLibraryRounded } from '@mui/icons-material';
import { Box, Button, Stack, TextField, Typography } from '@mui/material';
import { addToWhiteList } from 'apis/browsing';
import { useRef, useState } from 'react';
import Webcam from 'react-webcam';
import { useSearchParams } from 'react-router';
import { useAppDispatch } from 'reducers/hooks';
import { showNotification } from 'reducers/feedback';

const FaceEnroll = ({ onUpdate }: { onUpdate: () => void }) => {
    const dispatch = useAppDispatch();
    const [searchParams] = useSearchParams();
    const device = searchParams.get('device') || '';

    const [name, setName] = useState('');
    const [images, setImages] = useState<string[]>([]);
    const [submitting, setSubmitting] = useState(false);
    const [webcamEnabled, setWebcamEnabled] = useState(false);
    const webcamRef = useRef<Webcam>(null);

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        Array.from(e.target.files || []).forEach((file) => {
            setImages((prev) => [...prev, URL.createObjectURL(file)]);
        });
    };

    const handleCapture = () => {
        const screenshot = webcamRef.current?.getScreenshot();
        if (screenshot) setImages((prev) => [...prev, screenshot]);
    };

    const handleRemove = (index: number) => {
        setImages((prev) => prev.filter((_, i) => i !== index));
    };

    const handleSubmit = () => {
        setSubmitting(true);
        addToWhiteList(device, images, name)
            .then(() => {
                dispatch(showNotification({ message: 'Face added to white list successfully!', type: 'success' }));
                onUpdate();
            })
            .catch((err) => {
                console.error('Error adding face to white list:', err);
                dispatch(showNotification({ message: 'Failed to add face to white list. Please try again.', type: 'error' }));
            })
            .finally(() => setSubmitting(false));
    };

    return (
        <Stack spacing={2} sx={{ p: 1, width: '100%', maxWidth: 480 }}>
            <Typography variant="h6">Add Face to White List</Typography>

            <TextField
                label="Name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                fullWidth
            />

            <Button variant="outlined" component="label" startIcon={<PhotoLibraryRounded />}>
                Upload Photos
                <input type="file" accept="image/*" multiple hidden onChange={handleFileChange} />
            </Button>

            {webcamEnabled ? (
                <Stack spacing={1}>
                    <Webcam
                        ref={webcamRef}
                        mirrored
                        screenshotFormat="image/jpeg"
                        videoConstraints={{ width: 480, height: 360, facingMode: 'user' }}
                        style={{ width: '100%', borderRadius: 8 }}
                    />
                    <Stack direction="row" spacing={1}>
                        <Button variant="contained" startIcon={<CameraAltRounded />} onClick={handleCapture}>
                            Capture
                        </Button>
                        <Button size="small" onClick={() => setWebcamEnabled(false)}>
                            Hide Camera
                        </Button>
                    </Stack>
                </Stack>
            ) : (
                <Button variant="outlined" startIcon={<CameraAltRounded />} onClick={() => setWebcamEnabled(true)}>
                    Use Camera
                </Button>
            )}

            {images.length > 0 && (
                <Stack spacing={1}>
                    <Typography variant="body2" color="text.secondary">
                        {images.length} photo{images.length > 1 ? 's' : ''} selected
                    </Typography>
                    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                        {images.map((src, i) => (
                            <Box key={i} sx={{ position: 'relative', display: 'inline-block' }}>
                                <img
                                    src={src}
                                    alt={`face ${i + 1}`}
                                    style={{ width: 80, height: 80, objectFit: 'cover', borderRadius: 4 }}
                                />
                                <Button
                                    size="small"
                                    color="error"
                                    onClick={() => handleRemove(i)}
                                    sx={{ position: 'absolute', top: 0, right: 0, minWidth: 0, p: 0.3 }}
                                >
                                    <DeleteRounded fontSize="small" />
                                </Button>
                            </Box>
                        ))}
                    </Stack>
                </Stack>
            )}

            <Button
                variant="contained"
                color="primary"
                onClick={handleSubmit}
                disabled={!name.trim() || images.length === 0 || submitting}
            >
                {submitting ? 'Adding…' : 'Add to White List'}
            </Button>
        </Stack>
    );
};

export default FaceEnroll;

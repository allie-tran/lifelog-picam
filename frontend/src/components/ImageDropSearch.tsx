import { uploadAndSegment } from 'apis/browsing';
import { ImageSearchRounded } from '@mui/icons-material';
import { Box, Button, Stack, Typography } from '@mui/material';
import { useCallback, useRef, useState } from 'react';
import { FileUploader } from 'react-drag-drop-files';
import { useNavigate } from 'react-router';
import Webcam from 'react-webcam';
import '../App.css';
import ModalWithCloseButton from './ModalWithCloseButton';
import { setLoading, showNotification } from 'reducers/feedback';
import { useAppDispatch } from 'reducers/hooks';

const frontCameraConstraints = {
    width: 720,
    height: 360,
    facingMode: 'user',
};

const rearCameraConstraints = {
    width: 720,
    height: 360,
    facingMode: { exact: 'environment' },
};

const ImageDropSearch = ({ visible = true }: { visible?: boolean }) => {
    const navigate = useNavigate();
    const dispatch = useAppDispatch();
    const [useCamera, setUseCamera] = useState(false);
    const [flipCamera, setFlipCamera] = useState(false);
    const [file, setFile] = useState<File | null>(null);
    const [url, setUrl] = useState<string | null>(null);
    const [visualisedSegments, setSegments] = useState<string>('');
    const webcamRef = useRef<Webcam>(null);

    const handleChange = (file: File | File[]) => {
        if (file instanceof File) {
            setFile(file);
        } else {
            setFile(file[0]);
        }
    };

    const capture = useCallback(() => {
        if (webcamRef.current) {
            const imageSrc = webcamRef.current.getScreenshot();
            if (imageSrc) {
                setUrl(imageSrc);
            }
        }
    }, [webcamRef]);

    const onSearch = (blobUrl: string) => {
        navigate(`/search?mode=similar&&query=${encodeURIComponent(blobUrl)}`);
    };

    const onSegment = async (blobUrl: string) => {
        try {
            dispatch(setLoading(true));
            const segments = await uploadAndSegment(blobUrl, []);
            setSegments(segments || '');
        } catch (err) {
            console.error('Segmentation failed:', err);
            dispatch(
                showNotification({
                    message: 'Segmentation failed. Please try again.',
                    type: 'error',
                })
            );
        } finally {
            dispatch(setLoading(false));
        }
    };

    return (
        <Stack
            direction="row"
            spacing={2}
            alignItems="flex-start"
            sx={{ display: visible ? 'flex' : 'none', width: '100%', pt: 1 }}
        >
            <ModalWithCloseButton
                open={visualisedSegments !== ''}
                onClose={() => setSegments('')}
            >
                <Box
                    sx={{ maxWidth: '400px' }}
                    src={visualisedSegments}
                    component="img"
                />
            </ModalWithCloseButton>
            {useCamera ? (
                <Stack
                    spacing={2}
                    alignItems="center"
                    sx={{ width: '100%', position: 'relative' }}
                >
                    <Stack direction="row" spacing={2} alignItems="center">
                        {url ? (
                            <>
                                <Box
                                    component="img"
                                    src={url}
                                    alt="Captured"
                                    sx={{
                                        maxWidth: '400px',
                                        objectFit: 'contain',
                                    }}
                                />
                                <Button
                                    color="error"
                                    onClick={() => {
                                        setUrl(null);
                                        setFile(null);
                                    }}
                                >
                                    Clear
                                </Button>
                            </>
                        ) : (
                            <>
                                <Webcam
                                    mirrored
                                    screenshotFormat="image/jpeg"
                                    ref={webcamRef}
                                    videoConstraints={
                                        flipCamera
                                            ? rearCameraConstraints
                                            : frontCameraConstraints
                                    }
                                ></Webcam>
                                <Stack spacing={1}>
                                    <Button onClick={capture}>Capture</Button>
                                    <Button
                                        onClick={() => setFlipCamera((f) => !f)}
                                    >
                                        Flip Camera
                                    </Button>
                                </Stack>
                            </>
                        )}
                    </Stack>
                    <Button
                        onClick={() => {
                            setUseCamera(false);
                            setUrl(null);
                        }}
                        sx={{
                            textTransform: 'none',
                            paddingX: 3,
                        }}
                    >
                        Back to Upload
                    </Button>
                </Stack>
            ) : (
                <Stack spacing={2} alignItems="center" sx={{ width: '100%' }}>
                    <FileUploader
                        name="file"
                        label="Upload an image to find similar ones"
                        multiple={false}
                        handleChange={handleChange}
                        types={['JPG', 'PNG', 'GIF', 'JPEG', 'BMP']}
                        classes="file-uploader"
                    >
                        <Stack
                            spacing={1}
                            justifyContent="center"
                            alignItems="center"
                            sx={{
                                padding: 2,
                                border: '1px dashed',
                                borderColor: 'rgb(220, 220, 220, 0.5)',
                                borderRadius: 2,
                                cursor: 'pointer',
                                width: '100%',
                                '&:hover': {
                                    borderColor: 'primary.main',
                                },
                            }}
                        >
                            <ImageSearchRounded sx={{ fontSize: 32 }} />
                            <Typography>
                                Click or drag an image here to search for
                                similar ones
                            </Typography>
                            {file && (
                                <>
                                    <img
                                        src={URL.createObjectURL(file)}
                                        alt="Uploaded"
                                        style={{
                                            maxWidth: '200px',
                                            maxHeight: '200px',
                                            objectFit: 'contain',
                                        }}
                                    />
                                </>
                            )}
                        </Stack>
                    </FileUploader>
                    <Button
                        onClick={() => setUseCamera(true)}
                        sx={{
                            textTransform: 'none',
                            paddingX: 3,
                        }}
                    >
                        Use Camera
                    </Button>
                </Stack>
            )}

            <Stack sx={{ paddingTop: '1px' }} spacing={2} alignItems="center">
                <Button
                    variant="outlined"
                    onClick={() => {
                        if (useCamera && url) {
                            onSegment(url);
                        } else if (file) {
                            const blobUrl = URL.createObjectURL(file);
                            onSegment(blobUrl);
                        }
                    }}
                    sx={{
                        padding: 1.5,
                        outline: '2px solid',
                        minWidth: '100px',
                    }}
                >
                    <strong>Segment</strong>
                </Button>
                <Button
                    variant="outlined"
                    onClick={() => {
                        if (useCamera && url) {
                            onSearch(url);
                        } else if (file) {
                            const blobUrl = URL.createObjectURL(file);
                            onSearch(blobUrl);
                        }
                    }}
                    sx={{
                        padding: 1.5,
                        outline: '2px solid',
                        minWidth: '100px',
                    }}
                >
                    <strong>Lookup</strong>
                </Button>
                {file && (
                    <Button
                        onClick={(e) => {
                            e.stopPropagation();
                            setFile(null);
                        }}
                        color="error"
                        sx={{
                            textTransform: 'none',
                            paddingX: 3,
                        }}
                    >
                        Clear
                    </Button>
                )}
            </Stack>
        </Stack>
    );
};

export default ImageDropSearch;

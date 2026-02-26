import { uploadAndSegment } from 'apis/browsing';
import { ImageSearchRounded } from '@mui/icons-material';
import {
    Box,
    Button,
    FormControl,
    InputLabel,
    MenuItem,
    Select,
    Stack,
    Typography,
} from '@mui/material';
import { useCallback, useEffect, useRef, useState } from 'react';
import { FileUploader } from 'react-drag-drop-files';
import { useNavigate } from 'react-router';
import Webcam from 'react-webcam';
import '../App.css';
import ModalWithCloseButton from './ModalWithCloseButton';
import { setLoading, showNotification } from 'reducers/feedback';
import { useAppDispatch } from 'reducers/hooks';

const frontCameraConstraints = {
    width: 400,
    height: 200,
    facingMode: 'user',
};

const rearCameraConstraints = {
    width: 400,
    height: 200,
    facingMode: { exact: 'environment' },
};

// base64 to blob url
const base64ToBlobUrl = (base64: string): string => {
    const base64Data = base64.split(',')[1]; // Remove the data URL prefix
    const byteCharacters = atob(base64Data);
    const byteNumbers = new Array(byteCharacters.length);
    for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i);
    }
    const byteArray = new Uint8Array(byteNumbers);
    const blob = new Blob([byteArray], { type: 'image/png' });
    return URL.createObjectURL(blob);
};


// Helper to apply mask on the frontend
const applyMaskToImage = async (
    originalBlobUrl: string,
    maskBase64: string,
    bbox: number[]
): Promise<string> => {
    return new Promise((resolve) => {
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d')!;
        const img = new Image();
        const mask = new Image();

        img.onload = () => {
            canvas.width = img.width;
            canvas.height = img.height;
            mask.src = `data:image/png;base64,${maskBase64}`;
            mask.onload = () => {
                // 1. Draw the mask to the canvas first
                ctx.drawImage(mask, 0, 0, img.width, img.height);

                // 2. Convert white pixels to opaque and black to transparent
                const imageData = ctx.getImageData(
                    0,
                    0,
                    canvas.width,
                    canvas.height
                );
                const data = imageData.data;
                for (let i = 0; i < data.length; i += 4) {
                    // Use the red channel (data[i]) as the alpha (data[i+3])
                    // If it's white (255), it stays 255. If black (0), it becomes 0.
                    data[i + 3] = data[i];
                }
                ctx.putImageData(imageData, 0, 0);

                // 3. Draw the original image "into" the transparent mask
                ctx.globalCompositeOperation = 'source-in';
                ctx.drawImage(img, 0, 0);

                // 4. Draw the background as blurred original image
                ctx.globalCompositeOperation = 'destination-over';
                ctx.filter = 'blur(8px)';
                ctx.drawImage(img, 0, 0);

                // 5. Crop to bounding box with padding
                const [x, y, w, h] = bbox;
                const padding = Math.floor(Math.min(w, h) * 0.1);
                const croppedCanvas = document.createElement('canvas');
                const croppedCtx = croppedCanvas.getContext('2d')!;
                croppedCanvas.width = w + (padding * 2);
                croppedCanvas.height = h + (padding * 2);
                croppedCtx.drawImage(
                    canvas,
                    x - padding, y - padding, w + (padding * 2), h + (padding * 2),
                    0, 0, w + (padding * 2), h + (padding * 2)
                );
                resolve(croppedCanvas.toDataURL('image/jpeg', 0.95));

            };
        };
        img.src = originalBlobUrl;
    });
};

const ImageDropSearch = ({ visible = true }: { visible?: boolean }) => {
    const navigate = useNavigate();
    const dispatch = useAppDispatch();
    const webcamRef = useRef<Webcam>(null);

    const [useCamera, setUseCamera] = useState(true);
    const [flipCamera, setFlipCamera] = useState(false);

    const [url, setUrl] = useState<string | null>(null);

    const [visualised, setVisualised] = useState<string>('');
    const [maskedImage, setMaskedImage] = useState<string>('');
    const [masks, setMasks] = useState<string[]>([]);
    const [bboxes, setBboxes] = useState<number[][]>([]);
    const [selectedSegment, setSelectedSegment] = useState<number | 'all'>(
        'all'
    );

    const handleChange = (file: File | File[]) => {
        let blobUrl: string;
        if (file instanceof File) {
            blobUrl = URL.createObjectURL(file);
        } else {
            blobUrl = URL.createObjectURL(file[0]);
        }
        setUrl(blobUrl);
    };

    const capture = useCallback(() => {
        if (webcamRef.current) {
            const imageSrc = webcamRef.current.getScreenshot();
            if (imageSrc) {
                setUrl(imageSrc);
            }
        }
    }, [webcamRef]);

    const onSearch = (blobUrl: string | null) => {
        if (!blobUrl) return;
        setUrl(blobUrl);
        navigate(`/search?mode=similar&&query=${encodeURIComponent(blobUrl)}`);
    };

    const onSegment = async (blobUrl: string | null) => {
        if (!blobUrl) return;
        try {
            dispatch(setLoading(true));
            const data = await uploadAndSegment(blobUrl, []);
            if (!data) return;
            setVisualised(data.visualisation);
            setMaskedImage(data.visualisation);
            setMasks(data.masks);
            setBboxes(data.bboxes);
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

    useEffect(() => {
        if (!url) return;
        // change visualisedSegments when selectedSegment changes
        if (selectedSegment === 'all') {
            setMaskedImage(visualised);
        } else {
            // apply mask to image
            const maskBase64 = masks[selectedSegment];
            applyMaskToImage(url, maskBase64, bboxes[selectedSegment]).then(setMaskedImage);
        }
    }, [selectedSegment, masks, visualised, url]);

    return (
        <Stack
            direction="row"
            spacing={2}
            alignItems="flex-start"
            sx={{ display: visible ? 'flex' : 'none', width: '100%', pt: 1 }}
        >
            <ModalWithCloseButton
                open={visualised !== ''}
                onClose={() => setVisualised('')}
            >
                <Stack spacing={2} sx={{ minWidth: 150 }} direction="row">
                    <Box
                        sx={{
                            maxWidth: '90vw',
                            maxHeight: '80vh',
                            objectFit: 'contain',
                        }}
                        src={maskedImage}
                        component="img"
                    />
                    <Stack spacing={2}>
                        {masks.length > 0 && (
                            <FormControl fullWidth>
                                <InputLabel>Target Object</InputLabel>
                                <Select
                                    value={selectedSegment}
                                    label="Target Object"
                                    onChange={(e) =>
                                        setSelectedSegment(
                                            e.target.value as any
                                        )
                                    }
                                >
                                    <MenuItem value="all">
                                        Entire Image
                                    </MenuItem>
                                    {masks.map((_, index) => (
                                        <MenuItem key={index} value={index}>
                                            Object {index}
                                        </MenuItem>
                                    ))}
                                </Select>
                            </FormControl>
                        )}
                        <Button
                            onClick={() => {
                                onSearch(
                                    base64ToBlobUrl(maskedImage)
                                );
                                setVisualised('');
                            }}
                        >
                            Lookup Similar
                        </Button>
                    </Stack>
                </Stack>
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
                            {url && (
                                <img
                                    src={url}
                                    alt="Uploaded"
                                    style={{
                                        maxWidth: '200px',
                                        maxHeight: '200px',
                                        objectFit: 'contain',
                                    }}
                                />
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
                    disabled={!url}
                    onClick={() => {
                        onSegment(url);
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
                    disabled={!url}
                    onClick={() => {
                        onSearch(url);
                    }}
                    sx={{
                        padding: 1.5,
                        outline: '2px solid',
                        minWidth: '100px',
                    }}
                >
                    <strong>Lookup</strong>
                </Button>
                {url && (
                    <Button
                        onClick={(e) => {
                            e.stopPropagation();
                            setUrl(null);
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

import {
    AccessTimeRounded,
    DeleteRounded,
    DownloadRounded,
    EditRounded,
    ImageRounded,
    LocationOnRounded,
} from '@mui/icons-material';
import {
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    CircularProgress,
    Divider,
    Grid,
    Stack,
    Typography,
} from '@mui/material';
import { ImageWithMetadata, ObjectDetection } from '@utils/types';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import { clearZoomedImage } from 'reducers/zoomedImage';
import useSWR from 'swr';
import { deleteImage, getImage } from '../apis/browsing';
import { IMAGE_HOST_URL } from '../constants/urls';
import Annotator from './Annotator';
import ModalWithCloseButton from './ModalWithCloseButton';

const ImageZoom = ({ onDelete }: { onDelete?: (imgPath?: string) => void }) => {
    const dispatch = useAppDispatch();
    const navigate = useNavigate();
    const deviceId = useAppSelector((state) => state.auth.deviceId) || '';
    const [showAnnotator, setShowAnnotator] = useState(false);
    const { image: imagePath, isVideo } = useAppSelector(
        (state: any) => state.zoomedImage
    );

    const { data: imageData, isLoading } = useSWR(imagePath, async () =>
        getImage(deviceId, imagePath || '')
    );

    const handleDownload = () => {
        const link = document.createElement('a');
        link.href = imagePath;
        link.download = imagePath.split('/').pop() || 'image.jpg';
        document.body.appendChild(link);
        link.click();
    };

    const handleDelete = () => {
        deleteImage(deviceId, imagePath)
            .then(() => {
                dispatch(clearZoomedImage());
                onDelete && onDelete(imagePath);
            })
            .catch((err: any) => {
                console.error('Failed to delete image:', err);
            });
    };

    const handleSimilarImages = () => {
        dispatch(clearZoomedImage());
        navigate(
            '/search?mode=id&&query=' +
                encodeURIComponent(imagePath || '') +
                '&device=' +
                deviceId
        );
    };

    if (!imagePath) {
        return null;
    }

    console.log(imageData);

    return (
        <ModalWithCloseButton
            open={true}
            onClose={() => dispatch(clearZoomedImage())}
        >
            <Stack
                direction="row"
                spacing={2}
                alignItems="center"
                marginBottom={2}
            >
                <Button variant="outlined" onClick={handleSimilarImages}>
                    <ImageRounded sx={{ marginRight: 1 }} />
                    Similar Images
                </Button>
                <Button
                    onClick={handleDownload}
                    variant="outlined"
                    color="primary"
                >
                    <DownloadRounded sx={{ marginRight: 1 }} />
                    Download
                </Button>
                <Button
                    variant="outlined"
                    onClick={() => setShowAnnotator((prev) => !prev)}
                    color="secondary"
                >
                    <EditRounded sx={{ marginRight: 1 }} />
                    Annotate
                </Button>
                <Button variant="outlined" color="error" onClick={handleDelete}>
                    <DeleteRounded sx={{ marginRight: 1 }} />
                    Delete
                </Button>
            </Stack>
            {showAnnotator ? (
                <Box
                    sx={{
                        width: '100%',
                        height: '80dvh',
                        position: 'relative',
                        zIndex: 1,
                    }}
                >
                    <Annotator
                        image={{
                            imagePath: imagePath,
                            timestamp: new Date().toISOString(),
                            timezone: imageData?.timezone || 'UTC',
                            thumbnail: imagePath,
                            isVideo: isVideo,
                        }}
                    />
                </Box>
            ) : isVideo ? (
                <video
                    controls
                    autoPlay
                    style={{
                        maxWidth: '100%',
                        maxHeight: 'calc(80vh - 64px)',
                        borderRadius: '8px',
                        transform: 'rotate(90deg)',
                        transformOrigin: 'top left',
                    }}
                >
                    <source
                        src={`${IMAGE_HOST_URL}/${deviceId}/${imagePath}`}
                        type="video/mp4"
                    />
                </video>
            ) : isLoading ? (
                <CircularProgress size="3rem" />
            ) : (
                <Stack direction="column" alignItems="center" spacing={2}>
                    <img
                        src={imageData?.imagePath}
                        alt="Zoomed"
                        style={{
                            maxWidth: '100%',
                            maxHeight: 'calc(90dvh - 112px)',
                            borderRadius: '8px',
                        }}
                    />
                    <ImageVisualizer data={imageData as any} />
                </Stack>
            )}
        </ModalWithCloseButton>
    );
};

interface ImageVisualizerProps {
    data: ImageWithMetadata;
}

export const ImageVisualizer: React.FC<ImageVisualizerProps> = ({ data }) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const imageRef = useRef<HTMLImageElement>(null);
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const [hoveredBox, setHoveredBox] = useState<ObjectDetection | null>(null);

    // Combine objects and people for rendering, adding a type flag for coloring
    const allDetections = [
        ...data.objects.map((obj) => ({ ...obj, type: 'object' })),
        ...data.people.map((p) => ({ ...p, type: 'person' })),
    ];

    const drawBoundingBoxes = () => {
        const canvas = canvasRef.current;
        const img = imageRef.current;
        if (!canvas || !img) return;

        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        // Match canvas dimensions to the displayed image dimensions
        canvas.width = img.clientWidth;
        canvas.height = img.clientHeight;

        // Clear previous drawings
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Get natural image dimensions to calculate scale factors
        const scaleX = img.clientWidth / img.naturalWidth;
        const scaleY = img.clientHeight / img.naturalHeight;

        allDetections.forEach((det) => {
            let [xMin, yMin, xMax, yMax] = det.bbox; // relative
            const imgWidth = img.naturalWidth;
            const imgHeight = img.naturalHeight;

            // Scale coordinates to fit current UI size
            const x = xMin * scaleX * imgWidth;
            const y = yMin * scaleY * imgHeight;
            const width = (xMax - xMin) * scaleX * imgWidth;
            const height = (yMax - yMin) * scaleY * imgHeight;

            const isHovered =
                hoveredBox?.label === det.label &&
                hoveredBox?.bbox.toString() === det.bbox.toString();
            const color = det.type === 'person' ? '#ff1744' : '#00e676'; // Red for people, Green for objects

            // Draw Box
            ctx.strokeStyle = color;
            ctx.lineWidth = isHovered ? 4 : 2;
            ctx.strokeRect(x, y, width, height);

            // Draw Label Background
            ctx.fillStyle = color;
            ctx.font = '12px Roboto, sans-serif';
            const label = `${det.label} (${Math.round(det.confidence * 100)}%)`;
            const textWidth = ctx.measureText(label).width;

            ctx.fillRect(x, y - 20 >= 0 ? y - 20 : y, textWidth + 10, 20);

            // Draw Label Text
            ctx.fillStyle = '#ffffff';
            ctx.fillText(label, x + 5, y - 20 >= 0 ? y - 6 : y + 14);
        });
    };

    // Redraw whenever data changes, or window resizes
    useEffect(() => {
        const img = imageRef.current;
        if (img) {
            if (img.complete) {
                drawBoundingBoxes();
            } else {
                img.onload = drawBoundingBoxes;
            }
        }

        window.addEventListener('resize', drawBoundingBoxes);
        return () => window.removeEventListener('resize', drawBoundingBoxes);
    }, [data, hoveredBox]);

    return (
        <Grid
            container
            spacing={3}
            sx={{ p: 3, maxWidth: 1200, margin: '0 auto' }}
        >
            {/* Left Column: Image Canvas Overlay */}
            <Grid size={{ xs: 12, md: 7 }}>
                <Box
                    ref={containerRef}
                    sx={{
                        position: 'relative',
                        width: '100%',
                        borderRadius: 2,
                        overflow: 'hidden',
                        boxShadow: 3,
                        backgroundColor: '#000',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                    }}
                >
                    <img
                        ref={imageRef}
                        src={data.imagePath}
                        alt="Source"
                        style={{
                            width: '100%',
                            height: 'auto',
                            display: 'block',
                        }}
                    />
                    <canvas
                        ref={canvasRef}
                        style={{
                            position: 'absolute',
                            top: 0,
                            left: 0,
                            pointerEvents: 'none', // Allows mouse interactions to pass through if needed
                        }}
                    />
                </Box>
            </Grid>

            {/* Right Column: Metadata Panels */}
            <Grid size={{ xs: 12, md: 5 }}>
                <Stack spacing={2}>
                    {/* Info Card */}
                    <Card variant="outlined">
                        <CardContent>
                            <Typography
                                variant="h6"
                                gutterBottom
                                fontWeight="bold"
                            >
                                Image Metadata
                            </Typography>
                            <Stack spacing={1.5}>
                                <Box
                                    sx={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: 1,
                                    }}
                                >
                                    <AccessTimeRounded color="action" />
                                    <Typography variant="body2">
                                        {new Date(
                                            data.timestamp
                                        ).toLocaleString()}{' '}
                                        ({data.timezone})
                                    </Typography>
                                </Box>
                                {data.location && (
                                    <Box
                                        sx={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: 1,
                                        }}
                                    >
                                        <LocationOnRounded color="action" />
                                        <Typography variant="body2">
                                            {data.location.name}{' '}
                                            <Typography
                                                variant="caption"
                                                color="text.secondary"
                                            >
                                                ({data.gps.latitude},{' '}
                                                {data.gps.longitude})
                                            </Typography>
                                        </Typography>
                                    </Box>
                                )}
                            </Stack>
                        </CardContent>
                    </Card>

                    {/* Detections List Card */}
                    <Card variant="outlined">
                        <CardContent>
                            <Typography variant="h6" gutterBottom>
                                Detected Elements
                            </Typography>

                            {/* People Section */}
                            <Typography
                                variant="subtitle2"
                                color="text.secondary"
                                sx={{ mt: 1, mb: 1 }}
                            >
                                People ({data.people.length})
                            </Typography>
                            <Box
                                sx={{
                                    display: 'flex',
                                    flexWrap: 'wrap',
                                    gap: 1,
                                    mb: 2,
                                }}
                            >
                                {data.people.map((person, index) => (
                                    <Chip
                                        key={`person-${index}`}
                                        label={`${person.label} ${Math.round(person.confidence * 100)}%`}
                                        color="error"
                                        variant="outlined"
                                        onMouseEnter={() =>
                                            setHoveredBox(person)
                                        }
                                        onMouseLeave={() => setHoveredBox(null)}
                                        sx={{
                                            cursor: 'pointer',
                                            '&:hover': {
                                                backgroundColor: '#ffebee',
                                            },
                                        }}
                                    />
                                ))}
                                {data.people.length === 0 && (
                                    <Typography variant="caption">
                                        No people detected
                                    </Typography>
                                )}
                            </Box>

                            <Divider sx={{ my: 1.5 }} />

                            {/* Objects Section */}
                            <Typography
                                variant="subtitle2"
                                color="text.secondary"
                                sx={{ mb: 1 }}
                            >
                                Objects ({data.objects.length})
                            </Typography>
                            <Box
                                sx={{
                                    display: 'flex',
                                    flexWrap: 'wrap',
                                    gap: 1,
                                }}
                            >
                                {data.objects.map((obj, index) => (
                                    <Chip
                                        key={`obj-${index}`}
                                        label={`${obj.label} ${Math.round(obj.confidence * 100)}%`}
                                        color="success"
                                        variant="outlined"
                                        onMouseEnter={() => setHoveredBox(obj)}
                                        onMouseLeave={() => setHoveredBox(null)}
                                        sx={{
                                            cursor: 'pointer',
                                            '&:hover': {
                                                backgroundColor: '#e8f5e9',
                                            },
                                        }}
                                    />
                                ))}
                                {data.objects.length === 0 && (
                                    <Typography variant="caption">
                                        No objects detected
                                    </Typography>
                                )}
                            </Box>
                        </CardContent>
                    </Card>
                </Stack>
            </Grid>
        </Grid>
    );
};

export { ImageZoom };

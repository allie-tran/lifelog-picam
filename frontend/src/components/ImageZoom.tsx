import {
    AccessTimeRounded,
    CategoryRounded,
    DeleteRounded,
    DownloadRounded,
    EditRounded,
    ImageRounded,
    LocationOnRounded,
    PeopleRounded,
} from '@mui/icons-material';
import {
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    CircularProgress,
    Grid,
    Stack,
    Typography
} from '@mui/material';
import { ImageWithMetadata, ObjectDetection, PersonDetection } from '@utils/types';
import { getAllFaces } from '../apis/searchFilters';
import dayjs from 'dayjs';
import timezone from 'dayjs/plugin/timezone';
import utc from 'dayjs/plugin/utc';
import L from 'leaflet';
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png';
import markerIcon from 'leaflet/dist/images/marker-icon.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';
import 'leaflet/dist/leaflet.css';
import { useEffect, useRef, useState } from 'react';
import { MapContainer, Marker, TileLayer } from 'react-leaflet';
import { useNavigate, useSearchParams } from 'react-router';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import { clearZoomedImage } from 'reducers/zoomedImage';
import useSWR from 'swr';
import { deleteImage, getImage } from '../apis/browsing';
import { IMAGE_HOST_URL } from '../constants/urls';
import Annotator from './Annotator';
import ModalWithCloseButton from './ModalWithCloseButton';

dayjs.extend(utc);
dayjs.extend(timezone);

// Fix leaflet default marker icons (webpack/vite strips them otherwise)
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
    iconUrl: markerIcon,
    iconRetinaUrl: markerIcon2x,
    shadowUrl: markerShadow,
});

const BORING_NAMES = new Set(['---', 'Unknown Place', 'Unknown', '']);

const ImageZoom = ({ onDelete }: { onDelete?: (imgPath?: string) => void }) => {
    const dispatch = useAppDispatch();
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const device = searchParams.get('device') || '';
    const [showAnnotator, setShowAnnotator] = useState(false);
    const { image: imagePath, isVideo } = useAppSelector(
        (state: any) => state.zoomedImage
    );

    const { data: imageData, isLoading } = useSWR(imagePath, async () =>
        getImage(device, imagePath || '')
    );

    const handleDownload = () => {
        const link = document.createElement('a');
        link.href = imagePath;
        link.download = imagePath.split('/').pop() || 'image.jpg';
        document.body.appendChild(link);
        link.click();
    };

    const handleDelete = () => {
        deleteImage(device, imagePath)
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
                device
        );
    };

    if (!imagePath) {
        return null;
    }

    return (
        <ModalWithCloseButton
            open={true}
            onClose={() => dispatch(clearZoomedImage())}
        >
            <Stack direction="row" spacing={2} alignItems="center" marginBottom={2}>
                <Button variant="outlined" onClick={handleSimilarImages}>
                    <ImageRounded sx={{ marginRight: 1 }} />
                    Similar Images
                </Button>
                <Button onClick={handleDownload} variant="outlined" color="primary">
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
                <Box sx={{ width: '100%', height: '80dvh', position: 'relative', zIndex: 1 }}>
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
                        src={`${IMAGE_HOST_URL}/${device}/${imagePath}`}
                        type="video/mp4"
                    />
                </video>
            ) : isLoading ? (
                <CircularProgress size="3rem" />
            ) : (
                <ImageVisualizer data={imageData as any} />
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
    const [showBBoxes, setShowBBoxes] = useState(true);
    const [searchParams] = useSearchParams();
    const device = searchParams.get('device') || '';

    const { data: allFaces } = useSWR(
        device && data.people.length > 0 ? [device, 'faces'] : null,
        () => getAllFaces(device),
        { revalidateOnFocus: false }
    );

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

        canvas.width = img.clientWidth;
        canvas.height = img.clientHeight;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        if (!showBBoxes) return;

        const scaleX = img.clientWidth / img.naturalWidth;
        const scaleY = img.clientHeight / img.naturalHeight;

        allDetections.forEach((det) => {
            const [xMin, yMin, xMax, yMax] = det.bbox;
            const x = xMin * scaleX * img.naturalWidth;
            const y = yMin * scaleY * img.naturalHeight;
            const width = (xMax - xMin) * scaleX * img.naturalWidth;
            const height = (yMax - yMin) * scaleY * img.naturalHeight;

            const isHovered =
                hoveredBox?.label === det.label &&
                hoveredBox?.bbox.toString() === det.bbox.toString();
            const color = det.type === 'person' ? '#ff1744' : '#00e676';

            ctx.strokeStyle = color;
            ctx.lineWidth = isHovered ? 4 : 2;
            ctx.strokeRect(x, y, width, height);

            ctx.fillStyle = color;
            ctx.font = '12px Roboto, sans-serif';
            const label = `${det.label} (${Math.round(det.confidence * 100)}%)`;
            const textWidth = ctx.measureText(label).width;
            ctx.fillRect(x, y - 20 >= 0 ? y - 20 : y, textWidth + 10, 20);
            ctx.fillStyle = '#ffffff';
            ctx.fillText(label, x + 5, y - 20 >= 0 ? y - 6 : y + 14);
        });
    };

    useEffect(() => {
        const img = imageRef.current;
        if (img) {
            if (img.complete) drawBoundingBoxes();
            else img.onload = drawBoundingBoxes;
        }
        window.addEventListener('resize', drawBoundingBoxes);
        return () => window.removeEventListener('resize', drawBoundingBoxes);
    }, [data, hoveredBox, showBBoxes]);

    const tz = data.timezone || 'UTC';
    const formattedTime = dayjs.utc(data.timestamp).tz(tz).format('ddd D MMM YYYY, HH:mm z');

    const loc = data.location;
    const locName = loc?.name && !BORING_NAMES.has(loc.name) ? loc.name : null;
    const locParts = [locName, loc?.address].filter(Boolean).join(', ');
    const locLine = [locParts, loc?.country].filter(Boolean).join(' · ');

    const hasGps = data.gps && typeof data.gps.latitude === 'number' && typeof data.gps.longitude === 'number';

    return (
        <Grid container spacing={3} sx={{ p: 3, maxWidth: 1200, margin: '0 auto' }}>
            {/* Left: image with bbox overlay */}
            <Grid size={{ xs: 12, md: 7 }}>
                <Box
                    ref={containerRef}
                    sx={{
                        position: 'relative', width: '100%', borderRadius: 1,
                        overflow: 'hidden',
                        display: 'flex',
                        alignItems: 'center', justifyContent: 'center',
                    }}
                >
                    <img
                        ref={imageRef}
                        src={data.imagePath}
                        alt="Source"
                        style={{ width: '100%', maxHeight: 'calc(80dvh - 120px)', height: 'auto', display: 'block', objectFit: 'contain' }}
                    />
                    <canvas
                        ref={canvasRef}
                        style={{ position: 'absolute', top: 0, left: 0, pointerEvents: 'none' }}
                    />
                    {allDetections.length > 0 && (
                        <Button
                            size="small"
                            variant="contained"
                            onClick={(e) => { e.stopPropagation(); setShowBBoxes(v => !v); }}
                            sx={{
                                position: 'absolute', top: 8, right: 8, zIndex: 10,
                                minWidth: 0, fontSize: '0.7rem', py: 0.5, px: 1.5,
                                backgroundColor: showBBoxes ? 'rgba(0,0,0,0.65)' : 'rgba(80,80,80,0.5)',
                                '&:hover': { backgroundColor: 'rgba(0,0,0,0.85)' },
                            }}
                        >
                            {showBBoxes ? '🔲 Boxes' : '⬜ Boxes'}
                        </Button>
                    )}
                </Box>
            </Grid>

            {/* Right: metadata */}
            <Grid size={{ xs: 12, md: 5 }}>
                <Stack spacing={2}>
                    {/* Time + Location card */}
                    <Card variant="outlined">
                        <CardContent>
                            <Typography variant="h6" gutterBottom fontWeight="bold">
                                When &amp; Where
                            </Typography>
                            <Stack spacing={1.5}>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                    <AccessTimeRounded color="action" sx={{ mt: -1 }} />
                                    <Box>
                                        <Typography variant="body2" fontWeight={500}>
                                            {formattedTime}
                                        </Typography>
                                    </Box>
                                </Box>

                                {(locLine || hasGps) && (
                                    <Stack direction="row" alignItems="center" gap={1}>
                                        <LocationOnRounded color="action" sx={{ mt: -1 }} />
                                        <Box sx={{ flex: 1, minWidth: 0 }}>
                                            {locLine && (
                                                <Typography variant="body2" fontWeight={500} sx={{ mb: 0.5 }}>
                                                    {locLine}
                                                </Typography>
                                            )}
                                            {hasGps && (
                                                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                                                    {data.gps!.latitude.toFixed(5)}, {data.gps!.longitude.toFixed(5)}
                                                </Typography>
                                            )}
                                        </Box>
                                    </Stack>
                                )}

                                {hasGps && (
                                    <Box sx={{ height: 180, borderRadius: 1, overflow: 'hidden', mt: 0.5 }}>
                                        <MapContainer
                                            center={[data.gps!.latitude, data.gps!.longitude]}
                                            zoom={15}
                                            style={{ height: '100%', width: '100%' }}
                                            zoomControl={true}
                                            scrollWheelZoom={false}
                                            attributionControl={false}
                                        >
                                            <TileLayer url="https://api.maptiler.com/maps/dataviz-v4/{z}/{x}/{y}.png?key=bcAmE6kzFa3YgI6GTxUH"/>
                                            <Marker position={[data.gps!.latitude, data.gps!.longitude]} />
                                        </MapContainer>
                                    </Box>
                                )}
                            </Stack>
                        </CardContent>
                    </Card>

                    {/* People */}
                    {data.people.length > 0 && (
                        <Card variant="outlined">
                            <CardContent>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
                                    <PeopleRounded color="error" fontSize="small" />
                                    <Typography variant="h6" fontWeight="bold">
                                        People ({data.people.length})
                                    </Typography>
                                </Box>
                                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>
                                    {data.people.map((person, i) => {
                                        const face = allFaces?.find(f => f.id === person.clusterId);
                                        const avatar = face?.images[0];
                                        const name = person.clusterName || person.label;
                                        return (
                                            <Box
                                                key={`person-${i}`}
                                                onMouseEnter={() => setHoveredBox(person)}
                                                onMouseLeave={() => setHoveredBox(null)}
                                                sx={{
                                                    display: 'flex', flexDirection: 'column',
                                                    alignItems: 'center', gap: 0.5,
                                                    cursor: 'pointer',
                                                    p: 1, borderRadius: 1,
                                                    border: '1px solid',
                                                    borderColor: hoveredBox === person ? 'error.main' : 'divider',
                                                    backgroundColor: hoveredBox === person ? '#ffebee' : 'transparent',
                                                    transition: 'all 0.15s',
                                                    minWidth: 64,
                                                }}
                                            >
                                                {avatar ? (
                                                    <img
                                                        src={avatar}
                                                        alt={name}
                                                        style={{
                                                            width: 36, height: 36,
                                                            borderRadius: '50%',
                                                            objectFit: 'cover',
                                                            border: '2px solid #ef5350',
                                                        }}
                                                    />
                                                ) : (
                                                    <Box sx={{
                                                        width: 36, height: 36, borderRadius: '50%',
                                                        backgroundColor: '#ffcdd2',
                                                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                                                        border: '2px solid #ef5350',
                                                    }}>
                                                        <PeopleRounded sx={{ color: '#ef5350', fontSize: 24 }} />
                                                    </Box>
                                                )}
                                                <Typography variant="caption" fontWeight={600} textAlign="center" noWrap sx={{ maxWidth: 72 }}>
                                                    {name}
                                                </Typography>
                                                <Typography variant="caption" color="text.secondary">
                                                    {Math.round(person.confidence * 100)}%
                                                </Typography>
                                            </Box>
                                        );
                                    })}
                                </Box>
                            </CardContent>
                        </Card>
                    )}

                    {/* Objects */}
                    {data.objects.length > 0 && (
                        <Card variant="outlined">
                            <CardContent>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
                                    <CategoryRounded color="success" fontSize="small" />
                                    <Typography variant="h6" fontWeight="bold">
                                        Objects ({data.objects.length})
                                    </Typography>
                                </Box>
                                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                                    {data.objects.map((obj, i) => (
                                        <Chip
                                            key={`obj-${i}`}
                                            label={`${obj.label} ${Math.round(obj.confidence * 100)}%`}
                                            color="success"
                                            variant="outlined"
                                            onMouseEnter={() => setHoveredBox(obj)}
                                            onMouseLeave={() => setHoveredBox(null)}
                                            sx={{ cursor: 'pointer', '&:hover': { backgroundColor: '#e8f5e9' } }}
                                        />
                                    ))}
                                </Box>
                            </CardContent>
                        </Card>
                    )}

                    {data.people.length === 0 && data.objects.length === 0 && (
                        <Card variant="outlined">
                            <CardContent>
                                <Typography variant="body2" color="text.secondary">
                                    No people or objects detected
                                </Typography>
                            </CardContent>
                        </Card>
                    )}
                </Stack>
            </Grid>
        </Grid>
    );
};

export { ImageZoom };

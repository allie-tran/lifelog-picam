import {
    Button,
    Chip,
    Divider,
    Stack,
    TextField,
    Tooltip,
    Typography,
} from '@mui/material';
import DirectionsWalkIcon from '@mui/icons-material/DirectionsWalk';
import LocationOnIcon from '@mui/icons-material/LocationOn';
import SendRounded from '@mui/icons-material/SendRounded';
import { GPSData, ImageObject, LocationData } from '@utils/types';
import { changeSegmentActivity } from 'apis/process';
import { submitImage } from 'apis/dres';
import ModalWithCloseButton from 'components/ModalWithCloseButton';
import { CONFIDENCE_COLOURS, THEME_COLORS } from 'constants/activityColors';
import dayjs from 'dayjs';
import React from 'react';
import { setLoading, showNotification } from 'reducers/feedback';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import { addSubmittedImages } from 'reducers/dres';
import { useSearchParams } from 'react-router';
import { setZoomedImage } from 'reducers/zoomedImage';
import '../App.css';
import ImageWithDate from '../components/ImageWithDate';
import { useOnInView } from 'react-intersection-observer';
import { setHighlightedTrack } from 'reducers/map';

const LifelogEvent = ({
    segment,
    onChange,
    deleteRow,
    fullTime = false,
    location,
    gpsList,
    inView,
}: {
    segment: ImageObject[];
    onChange: () => void;
    deleteRow: (imagePaths: string[]) => void;
    fullTime?: boolean;
    location?: LocationData;
    gpsList?: GPSData[];
    inView?: boolean;
}) => {
    const dispatch = useAppDispatch();
    const [searchParams] = useSearchParams();
    const device = searchParams.get('device') || '';
    const { evaluationId, sessionId, currentTask } = useAppSelector((s) => s.dres);
    const dresReady = !!(evaluationId && sessionId);
    const firstImage = segment[0];
    const lastImage = segment[segment.length - 1];
    const date = dayjs(firstImage.timestamp).format('YYYY-MM-DD');
    // const count = segment.length;
    const [edit, setEdit] = React.useState(false);
    const [activityEditText, setActivityEditText] = React.useState('');
    const handleDresSubmitEvent = () => {
        if (!dresReady) return;
        const paths = segment.map((img) => img.imagePath);
        dispatch(addSubmittedImages(paths));
        (async () => {
            try {
                let lastResult = null;
                for (const img of segment) {
                    lastResult = await submitImage({ image: img.imagePath, evaluationId: evaluationId!, sessionId: sessionId! });
                }
                const r = lastResult!;
                dispatch(showNotification({ message: `DRES: ${r.verdict} — submitted ${segment.length} images`, type: r.severity }));
            } catch {
                dispatch(showNotification({ message: 'DRES submit failed', type: 'error' }));
            }
        })();
    };
    const confidenceColor = CONFIDENCE_COLOURS[firstImage?.activityConfidence || ''];
    const groupColor = firstImage?.activityGroup ? THEME_COLORS[firstImage.activityGroup] : undefined;

    // Initialize the hook inside each item
    const trackingRef = useOnInView(
        (inView) => {
            if (inView) {
                dispatch(setHighlightedTrack(gpsList || []));
            }
        },
        { threshold: 0.5 } // Adjust based on how much of the card must be visible
    );

    return (
        <React.Fragment>
            <Stack
                ref={trackingRef}
                spacing={1}
                sx={{
                    height: 'fit-content',
                    // flex: count < 3 ? '1 0 500px' : '1 0 100%',
                    width: '100%',
                    justifyContent: 'flex-start',
                    backgroundColor: inView
                        ? 'rgba(0, 123, 255, 0.1)'
                        : 'transparent',
                    position: 'relative',
                    pt: 2,
                }}
            >
                <Divider />
                <Stack direction="row" spacing={1} alignItems="flex-start">
                    {location ? (
                        location.stop === false ? (
                            // ── Move segment ──────────────────────────────
                            <Stack direction="row" spacing={1} alignItems="center">
                                <DirectionsWalkIcon fontSize="small" color="action" />
                                <Stack>
                                    <Typography variant="subtitle2" fontWeight="medium">
                                        {location.name || 'Moving'}
                                    </Typography>
                                    <Typography variant="caption" color="textSecondary">
                                        {[location.city, location.region, location.country]
                                            .filter(Boolean)
                                            .join(', ')}
                                    </Typography>
                                </Stack>
                            </Stack>
                        ) : (
                            // ── Stop segment ──────────────────────────────
                            <Stack direction="row" spacing={1} alignItems="flex-start">
                                <LocationOnIcon fontSize="small" color="primary" sx={{ mt: 0.3 }} />
                                <Stack spacing={0.5}>
                                    <Stack direction="row" spacing={1} alignItems="center">
                                        <Typography variant="subtitle2" fontWeight="medium">
                                            {location.name || location.suburb || location.city || 'Unknown place'}
                                        </Typography>
                                        {location.categories && (
                                            <Chip
                                                label={location.categories.split(';')[0].trim()}
                                                size="small"
                                                variant="outlined"
                                                sx={{ height: 18, fontSize: '0.65rem' }}
                                            />
                                        )}
                                    </Stack>
                                    <Typography variant="caption" color="textSecondary">
                                        {[location.suburb, location.city, location.country]
                                            .filter(Boolean)
                                            .join(', ')}
                                        {location.postcode ? ` · ${location.postcode}` : ''}
                                    </Typography>
                                    {location.description && (
                                        <Tooltip title={location.description} arrow>
                                            <Typography
                                                variant="caption"
                                                color="textSecondary"
                                                sx={{
                                                    fontStyle: 'italic',
                                                    maxWidth: 400,
                                                    overflow: 'hidden',
                                                    textOverflow: 'ellipsis',
                                                    whiteSpace: 'nowrap',
                                                    cursor: 'default',
                                                }}
                                            >
                                                {location.description}
                                            </Typography>
                                        </Tooltip>
                                    )}
                                </Stack>
                            </Stack>
                        )
                    ) : (
                        <Typography variant="subtitle2" color="textSecondary">
                            No location data
                        </Typography>
                    )}
                </Stack>
                <Stack
                    direction="row"
                    justifyContent="space-between"
                    alignItems="center"
                >
                    <Stack
                        direction="row"
                        spacing={1}
                        flexShrink={0}
                        alignItems="center"
                    >
                        <Typography variant="subtitle1" fontWeight="bold" sx={{ textTransform: 'capitalize' }}>
                            {firstImage.activity || 'No Activity Detected'}
                        </Typography>
                        {firstImage.activityGroup && (
                            <Chip
                                label={firstImage.activityGroup}
                                size="small"
                                sx={{
                                    backgroundColor: groupColor,
                                    color: 'rgba(0,0,0,0.7)',
                                    height: 18,
                                    fontSize: '0.65rem',
                                }}
                            />
                        )}
                        {firstImage.activityConfidence && (
                            <Typography
                                variant="caption"
                                color={`${confidenceColor}.main` || 'text.secondary'}
                            >
                                {firstImage.activityConfidence}
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
                            <strong>
                                {dayjs(firstImage.timestamp).format('ll')}
                            </strong>
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
                            sx={{ textDecoration: 'underline', textTransform: 'none', p: 0 }}
                        >
                            Edit Activity Info
                        </Button>
                    ) : null}
                    <Button
                        color="error"
                        onClick={() => deleteRow(segment.map((img) => img.imagePath))}
                        sx={{ textDecoration: 'underline', textTransform: 'none', p: 0 }}
                    >
                        Delete Row
                    </Button>
                    {dresReady && (
                        <Tooltip title={currentTask ? `Submit to: ${currentTask.name}` : 'Submit event to DRES'}>
                            <Button
                                color="success"
                                onClick={handleDresSubmitEvent}
                                startIcon={<SendRounded />}
                                sx={{ textTransform: 'none', p: 0 }}
                            >
                                Submit Event
                            </Button>
                        </Tooltip>
                    )}
                </Stack>
                <Stack
                    direction="row"
                    spacing={2}
                    sx={{
                        maxWidth: '100vw',
                        width: '100%',
                        // overflowY: 'auto',
                        // height: '300px',
                        p: 0,
                        flexWrap: 'wrap',
                    }}
                    useFlexGap
                >
                    {segment.map((image: ImageObject) => (
                        <ImageWithDate
                            timeOnly
                            height={'200px'}
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
                                device,
                                date,
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

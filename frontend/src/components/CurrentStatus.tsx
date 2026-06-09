import {
    Box,
    Chip,
    Divider,
    Paper,
    Stack,
    Tooltip,
    Typography,
} from '@mui/material';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import DirectionsWalkIcon from '@mui/icons-material/DirectionsWalk';
import LocationOnIcon from '@mui/icons-material/LocationOn';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import { getCurrentStatus } from '../apis/process';
import { THUMBNAIL_HOST_URL } from '../constants/urls';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import useSWR from 'swr';

dayjs.extend(relativeTime);

const SENSOR_LABELS: Record<string, string> = {
    camera: 'Camera',
    location: 'GPS',
    heart_rate: 'Heart Rate',
    accelerometer: 'Motion',
    ppg: 'PPG',
};

function OnlineDot({ online }: { online: boolean }) {
    return (
        <FiberManualRecordIcon
            sx={{
                fontSize: 10,
                color: online ? 'success.main' : 'text.disabled',
                verticalAlign: 'middle',
            }}
        />
    );
}

export default function CurrentStatus({ deviceId }: { deviceId: string }) {
    const { data } = useSWR(
        deviceId ? ['current-status', deviceId] : null,
        () => getCurrentStatus(deviceId),
        { refreshInterval: 5 * 60 * 1000, revalidateOnFocus: false }
    );

    if (!data) return null;

    const thumbnailUrl = data.currentThumbnail
        ? `${THUMBNAIL_HOST_URL}/${deviceId}/${data.currentThumbnail}`
        : null;

    const cameraLastSeenText = data.cameraLastSeen
        ? dayjs(data.cameraLastSeen).fromNow()
        : 'Never';

    const segmentSinceText = data.segmentSince
        ? dayjs(data.segmentSince).fromNow()
        : null;

    return (
        <Paper
            variant="outlined"
            sx={{ p: 2, width: '100%', borderRadius: 2 }}
        >
            <Stack spacing={1.5}>
                {/* Header row */}
                <Stack direction="row" spacing={1.5} alignItems="center" justifyContent="space-between">
                    <Stack direction="row" spacing={1} alignItems="center">
                        <OnlineDot online={data.cameraOnline} />
                        <Typography variant="subtitle1" fontWeight="bold">
                            Current Status
                        </Typography>
                        {data.cameraOnline ? (
                            <Chip label="Live" size="small" color="success" sx={{ height: 18, fontSize: '0.65rem' }} />
                        ) : (
                            <Typography variant="caption" color="text.secondary">
                                Last seen {cameraLastSeenText}
                            </Typography>
                        )}
                    </Stack>

                    {/* Sensor dots */}
                    <Stack direction="row" spacing={1} alignItems="center">
                        {data.sensors.map((s) => (
                            <Tooltip
                                key={`${s.deviceId}-${s.sensorType}`}
                                title={`${s.nickname || SENSOR_LABELS[s.sensorType] || s.sensorType}: ${s.lastSeen ? dayjs(s.lastSeen).fromNow() : 'never'}`}
                                arrow
                            >
                                <Stack direction="row" spacing={0.3} alignItems="center" sx={{ cursor: 'default' }}>
                                    <OnlineDot online={s.online} />
                                    <Typography variant="caption" color="text.secondary">
                                        {s.nickname || SENSOR_LABELS[s.sensorType] || s.sensorType}
                                    </Typography>
                                </Stack>
                            </Tooltip>
                        ))}
                    </Stack>
                </Stack>

                <Divider />

                {/* Activity + location */}
                <Stack direction="row" spacing={2} alignItems="flex-start">
                    {thumbnailUrl && (
                        <Box
                            component="img"
                            src={thumbnailUrl}
                            sx={{
                                width: 72,
                                height: 72,
                                objectFit: 'cover',
                                borderRadius: 1,
                                flexShrink: 0,
                            }}
                        />
                    )}
                    <Stack spacing={0.5} flex={1} minWidth={0}>
                        {data.currentActivity && (
                            <Typography variant="body2" fontWeight="medium">
                                {data.currentActivity}
                            </Typography>
                        )}
                        {data.currentActivityDescription && (
                            <Typography
                                variant="caption"
                                color="text.secondary"
                                sx={{
                                    overflow: 'hidden',
                                    display: '-webkit-box',
                                    WebkitLineClamp: 2,
                                    WebkitBoxOrient: 'vertical',
                                }}
                            >
                                {data.currentActivityDescription}
                            </Typography>
                        )}

                        {/* Location */}
                        {data.currentLocation && (
                            <Stack direction="row" spacing={0.5} alignItems="center">
                                {data.currentLocation.stop === false ? (
                                    <DirectionsWalkIcon fontSize="inherit" color="action" />
                                ) : (
                                    <LocationOnIcon fontSize="inherit" color="primary" />
                                )}
                                <Typography variant="caption" color="text.secondary">
                                    {data.currentLocation.name ||
                                        data.currentLocation.suburb ||
                                        data.currentLocation.city ||
                                        'Unknown location'}
                                    {data.currentLocation.city &&
                                        data.currentLocation.name !== data.currentLocation.city &&
                                        `, ${data.currentLocation.city}`}
                                </Typography>
                            </Stack>
                        )}

                        {/* Since when */}
                        {segmentSinceText && (
                            <Stack direction="row" spacing={0.5} alignItems="center">
                                <AccessTimeIcon fontSize="inherit" color="action" />
                                <Typography variant="caption" color="text.secondary">
                                    Since {segmentSinceText}
                                </Typography>
                            </Stack>
                        )}
                    </Stack>
                </Stack>

                {/* LLM summary */}
                {data.summary && (
                    <>
                        <Divider />
                        <Typography variant="caption" color="text.secondary" sx={{ fontStyle: 'italic' }}>
                            {data.summary}
                        </Typography>
                    </>
                )}
            </Stack>
        </Paper>
    );
}

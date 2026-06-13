import {
    CheckRounded,
    CloseRounded,
    DeleteRounded,
    DevicesRounded,
    EditRounded,
    FiberManualRecordRounded,
} from '@mui/icons-material';
import {
    Box,
    Card,
    CardContent,
    Chip,
    CircularProgress,
    IconButton,
    Stack,
    TextField,
    Tooltip,
    Typography,
} from '@mui/material';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import React from 'react';
import useSWR from 'swr';
import { SensorStatus, getMySensors, renameSensor } from 'apis/profile';
import { removeSensorAccess } from 'apis/auth';
import { useAppSelector } from 'reducers/hooks';

dayjs.extend(relativeTime);

const ONLINE_THRESHOLD_MS = 5 * 60 * 1000;

const sensorColor: Record<string, 'primary' | 'secondary' | 'success' | 'default'> = {
    camera: 'primary',
    location: 'secondary',
    biometrics: 'success',
};

const DeviceCard = ({
    sensor,
    username,
    onChanged,
}: {
    sensor: SensorStatus;
    username: string | null;
    onChanged: () => void;
}) => {
    const [editing, setEditing] = React.useState(false);
    const [nickname, setNickname] = React.useState(sensor.deviceNickname ?? sensor.deviceId);
    const [busy, setBusy] = React.useState(false);

    const lastSeen = sensor.lastSeen ? dayjs(sensor.lastSeen) : null;
    const online = lastSeen ? Date.now() - lastSeen.valueOf() < ONLINE_THRESHOLD_MS : false;

    const handleRename = async () => {
        if (!nickname.trim()) return;
        setBusy(true);
        try {
            await renameSensor(sensor.deviceId, sensor.sensorType, nickname.trim());
            setEditing(false);
            onChanged();
        } finally {
            setBusy(false);
        }
    };

    const handleRemove = async () => {
        if (!username) return;
        if (!window.confirm(`Remove ${sensor.deviceNickname ?? sensor.deviceId}? This detaches the device from your account.`)) {
            return;
        }
        setBusy(true);
        try {
            await removeSensorAccess(username, sensor.deviceId, sensor.sensorType);
            onChanged();
        } finally {
            setBusy(false);
        }
    };

    return (
        <Card variant="outlined" sx={{ width: 300 }}>
            <CardContent>
                <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
                    {editing ? (
                        <Stack direction="row" spacing={0.5} alignItems="center" sx={{ flex: 1 }}>
                            <TextField
                                size="small"
                                value={nickname}
                                onChange={(e) => setNickname(e.target.value)}
                                autoFocus
                                fullWidth
                                onKeyDown={(e) => e.key === 'Enter' && handleRename()}
                            />
                            <IconButton size="small" color="primary" disabled={busy} onClick={handleRename}>
                                {busy ? <CircularProgress size={16} /> : <CheckRounded fontSize="small" />}
                            </IconButton>
                            <IconButton
                                size="small"
                                onClick={() => {
                                    setEditing(false);
                                    setNickname(sensor.deviceNickname ?? sensor.deviceId);
                                }}
                            >
                                <CloseRounded fontSize="small" />
                            </IconButton>
                        </Stack>
                    ) : (
                        <Stack direction="row" alignItems="center" spacing={0.5} sx={{ flex: 1, minWidth: 0 }}>
                            <Typography variant="subtitle1" fontWeight={700} noWrap>
                                {sensor.deviceNickname || sensor.deviceId}
                            </Typography>
                            <Tooltip title="Rename">
                                <IconButton size="small" onClick={() => setEditing(true)}>
                                    <EditRounded fontSize="small" />
                                </IconButton>
                            </Tooltip>
                        </Stack>
                    )}
                    <Tooltip title="Remove device">
                        <span>
                            <IconButton size="small" color="error" disabled={busy} onClick={handleRemove}>
                                <DeleteRounded fontSize="small" />
                            </IconButton>
                        </span>
                    </Tooltip>
                </Stack>

                <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.5 }}>
                    <Chip
                        size="small"
                        label={sensor.sensorType}
                        color={sensorColor[sensor.sensorType] ?? 'default'}
                        variant="outlined"
                    />
                    <Typography variant="caption" color="text.secondary" noWrap>
                        {sensor.deviceId}
                    </Typography>
                </Stack>

                <Stack direction="row" alignItems="center" spacing={0.5}>
                    <FiberManualRecordRounded
                        sx={{ fontSize: 12, color: online ? 'success.main' : 'text.disabled' }}
                    />
                    <Typography variant="caption" color="text.secondary">
                        {lastSeen ? `Last seen ${lastSeen.fromNow()}` : 'Never seen'}
                    </Typography>
                </Stack>
            </CardContent>
        </Card>
    );
};

const DevicesSection = () => {
    const username = useAppSelector((state) => state.auth.username);
    const { data: sensors, mutate, isLoading } = useSWR('my-sensors', getMySensors, {
        revalidateOnFocus: false,
    });

    return (
        <Box>
            <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
                <DevicesRounded color="primary" />
                <Typography variant="h6" color="primary">
                    Your Devices
                </Typography>
            </Stack>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                Sensors linked to your account. Rename or remove them here.
            </Typography>

            {isLoading && <CircularProgress size={20} />}
            {sensors && sensors.length === 0 && (
                <Typography variant="body2" color="text.secondary">
                    No devices linked to your account.
                </Typography>
            )}

            <Stack direction="row" flexWrap="wrap" spacing={2} useFlexGap>
                {sensors?.map((s) => (
                    <DeviceCard
                        key={`${s.deviceId}-${s.sensorType}`}
                        sensor={s}
                        username={username}
                        onChanged={() => mutate()}
                    />
                ))}
            </Stack>
        </Box>
    );
};

export default DevicesSection;

import {
    AddRounded,
    CameraAltRounded,
    MonitorHeartRounded,
    PersonRounded,
    VerifiedUserRounded,
} from '@mui/icons-material';
import {
    Button,
    Divider,
    FormControl,
    FormControlLabel,
    InputLabel,
    MenuItem,
    Select,
    Snackbar,
    Stack,
    Switch,
    TextField,
    Typography,
} from '@mui/material';
import { addSensorToUser, changeUserAccess, getUsers } from 'apis/auth';
import { getAllDeviceSettings, setRecognitionMode } from 'apis/browsing';
import ModalWithCloseButton from 'components/ModalWithCloseButton';
import React from 'react';
import { useCookies } from 'react-cookie';
import { useNavigate } from 'react-router';
import { useAppSelector } from 'reducers/hooks';
import useSWR from 'swr';
import { AccessLevel, DeviceAccess, SensorDevice, UserInfo } from 'types/auth';

const Admin = () => {
    const navigate = useNavigate();
    const { isAuthenticated } = useAppSelector((state) => state.auth);
    const [cookies] = useCookies(['token']);

    // Content Access Modal States
    const [open, setOpen] = React.useState(false);
    const [userForAccess, setUserForAccess] = React.useState<string | null>(
        null
    );
    const [device, setDevice] = React.useState<string>('');
    const [accessLevel, setAccessLevel] = React.useState<AccessLevel>(
        AccessLevel.NONE
    );

    // Sensor Access
    const [openSensor, setOpenSensor] = React.useState(false);
    const [userForSensorAccess, setUserForSensorAccess] = React.useState<
        string | null
    >(null);
    const [sensorDeviceId, setSensorDeviceId] = React.useState<string>('');
    const [sensorType, setSensorType] = React.useState<string>('');
    const [sensorSecret, setSensorSecret] = React.useState<string>('');
    const [deviceNickname, setDeviceNickname] = React.useState<string>('');

    if (!isAuthenticated) {
        navigate('/login');
    }

    const {
        data: users,
        error,
        mutate,
    } = useSWR('/api/admin/users', () => getUsers(cookies.token), {
        shouldRetryOnError: false,
    });

    const addContentAccessToUser = (
        username: string,
        device: string,
        accessLevel: AccessLevel
    ) => {
        changeUserAccess(cookies.token, username, device, accessLevel);
        mutate();
    };

    const [deviceSettingsSnackbar, setDeviceSettingsSnackbar] = React.useState<string | null>(null);

    const { data: deviceSettings, mutate: mutateDeviceSettings } = useSWR(
        '/api/face/all-device-settings',
        () => getAllDeviceSettings(),
        { shouldRetryOnError: false }
    );

    const handleToggleRecognitionMode = async (deviceId: string, keep: boolean) => {
        await setRecognitionMode(deviceId, keep);
        mutateDeviceSettings();
        setDeviceSettingsSnackbar(
            keep
                ? `${deviceId}: face recognition enabled — whitelist now controls labeling.`
                : `${deviceId}: switched to anonymous clustering.`
        );
    };

    const addSensorAccessToUser = async (
        device: string,
        sensorType: string,
        sensorSecret: string,
        deviceNickname: string,
        associatedUsername: string
    ) => {
        await addSensorToUser(
            device,
            sensorType,
            sensorSecret,
            deviceNickname,
            associatedUsername
        );
        mutate();
    };

    if (error) {
        return (
            <Typography variant="h6" align="center" marginTop={4}>
                Not authorized to view this page.
            </Typography>
        );
    }

    return (
        <Stack
            sx={{ width: '100%', px: 6 }}
            alignItems="flex-start"
            spacing={2}
        >
            <Typography variant="h4" marginBottom={4} width="100%">
                Admin Panel - User List
            </Typography>
            <Divider flexItem />
            {users?.map((user: UserInfo) => (
                <React.Fragment key={user.username}>
                    <Stack
                        direction="row"
                        justifyContent="space-between"
                        alignItems="center"
                        width="100%"
                    >
                        <Typography
                            key={user.username}
                            variant="h6"
                            align="center"
                            marginTop={2}
                            color="primary.main"
                        >
                            <PersonRounded
                                sx={{ mr: 1, verticalAlign: 'middle' }}
                            />
                            {user.username}
                        </Typography>
                        <Stack direction="row" spacing={1}>
                            <Button
                                variant="outlined"
                                sx={{ mt: 2, textTransform: 'none' }}
                                onClick={() => {
                                    setUserForAccess(user.username);
                                    setDevice('');
                                    setAccessLevel(AccessLevel.NONE);
                                    setOpen(true);
                                }}
                            >
                                Add Device Access <AddRounded sx={{ ml: 1 }} />
                            </Button>
                            <Button
                                variant="outlined"
                                sx={{ mt: 2, textTransform: 'none' }}
                                onClick={() => {
                                    setUserForSensorAccess(user.username);
                                    setSensorDeviceId('');
                                    setSensorType('');
                                    setSensorSecret('');
                                    setDeviceNickname('');
                                    setOpenSensor(true);
                                }}
                            >
                                Add Sensor Access <AddRounded sx={{ ml: 1 }} />
                            </Button>
                        </Stack>
                    </Stack>
                    <Stack
                        alignItems="flex-start"
                        spacing={1}
                        sx={{ width: '100%', mt: 1 }}
                    >
                        <Typography variant="subtitle1" color="text.secondary">
                            Content Access:
                        </Typography>
                        {user.devices ? (
                            user.devices.map((device: DeviceAccess) => (
                                <Stack
                                    direction="row"
                                    key={device.deviceId}
                                    alignItems="center"
                                    justifyContent="space-between"
                                    sx={{
                                        width: '100%',
                                        backgroundColor: 'background.paper',
                                        borderRadius: 1,
                                        border: '1px solid #424352',
                                        p: 1,
                                        px: 2,
                                    }}
                                >
                                    <Stack direction="row" alignItems="center">
                                        <CameraAltRounded
                                            sx={{
                                                mr: 1,
                                                verticalAlign: 'middle',
                                            }}
                                        />
                                        <Typography
                                            variant="body2"
                                            align="center"
                                        >
                                            {device.deviceId} -{' '}
                                            <strong>
                                                {device.accessLevel.toUpperCase()}
                                            </strong>
                                        </Typography>
                                    </Stack>
                                    <Button
                                        variant="text"
                                        color="error"
                                        sx={{ ml: 1, textTransform: 'none' }}
                                        onClick={() => {
                                            setUserForAccess(user.username);
                                            setDevice(device.deviceId);
                                            setAccessLevel(device.accessLevel);
                                            setOpen(true);
                                        }}
                                    >
                                        Modify
                                    </Button>
                                </Stack>
                            ))
                        ) : (
                            <Typography
                                variant="body2"
                                align="center"
                                marginTop={1}
                            >
                                No device access assigned.
                            </Typography>
                        )}
                        <Divider flexItem sx={{ my: 2 }} />
                        {user.sensors ? (
                            user.sensors.map((sensor: SensorDevice) => (
                                <Stack
                                    direction="row"
                                    key={sensor.deviceNickname} // Using nickname as key, or any unique identifier
                                    alignItems="center"
                                    justifyContent="space-between"
                                    sx={{
                                        width: '100%',
                                        backgroundColor: 'background.default',
                                        borderRadius: 1,
                                        border: '1px solid #424352',
                                        p: 1,
                                        px: 2,
                                    }}
                                >
                                    <Stack direction="row" alignItems="center">
                                        <MonitorHeartRounded
                                            sx={{
                                                mr: 1,
                                                verticalAlign: 'middle',
                                            }}
                                        />
                                        <Typography
                                            variant="body2"
                                            align="center"
                                        >
                                            {sensor.deviceNickname} -{' '}
                                            <strong>
                                                {sensor.sensorType.toUpperCase()}
                                            </strong>
                                        </Typography>
                                    </Stack>
                                    <Button
                                        variant="text"
                                        color="error"
                                        sx={{ ml: 1, textTransform: 'none' }}
                                        onClick={() => {
                                            setUserForSensorAccess(
                                                user.username
                                            );
                                            setSensorDeviceId(sensor.deviceId);
                                            setSensorType(sensor.sensorType);
                                            setDeviceNickname(
                                                sensor.deviceNickname
                                            );
                                            setSensorSecret(sensor.secret);
                                            setOpenSensor(true);
                                        }}
                                    >
                                        Modify
                                    </Button>
                                </Stack>
                            ))
                        ) : (
                            <Typography
                                variant="body2"
                                align="center"
                                marginTop={1}
                            >
                                No sensor access assigned.
                            </Typography>
                        )}
                    </Stack>
                </React.Fragment>
            ))}

            {/* Device Settings */}
            <Divider flexItem sx={{ my: 2 }} />
            <Typography variant="h5" sx={{ mb: 2 }}>
                Device Settings
            </Typography>
            <Snackbar
                open={deviceSettingsSnackbar !== null}
                autoHideDuration={5000}
                onClose={() => setDeviceSettingsSnackbar(null)}
                message={deviceSettingsSnackbar}
            />
            {deviceSettings?.map((ds) => (
                <Stack
                    key={ds.deviceId}
                    direction="row"
                    alignItems="center"
                    justifyContent="space-between"
                    sx={{
                        width: '100%',
                        backgroundColor: 'background.paper',
                        borderRadius: 1,
                        border: '1px solid #424352',
                        p: 1,
                        px: 2,
                        mb: 1,
                    }}
                >
                    <Stack direction="row" alignItems="center">
                        <CameraAltRounded sx={{ mr: 1, verticalAlign: 'middle' }} />
                        <Typography variant="body2">{ds.deviceId}</Typography>
                    </Stack>
                    <FormControlLabel
                        control={
                            <Switch
                                checked={ds.keepFaceRecognition}
                                onChange={(e) =>
                                    handleToggleRecognitionMode(ds.deviceId, e.target.checked)
                                }
                                size="small"
                            />
                        }
                        label={
                            <Typography variant="caption">
                                {ds.keepFaceRecognition ? 'Whitelist recognition' : 'Anonymous clustering'}
                            </Typography>
                        }
                    />
                </Stack>
            ))}

            <ModalWithCloseButton
                open={open}
                onClose={() => setOpen(false)}
                fitContent
            >
                <Stack spacing={2} sx={{ width: 400, p: 3 }}>
                    <Typography variant="h6" align="center" marginY={2}>
                        <VerifiedUserRounded
                            sx={{ mr: 1, verticalAlign: 'middle' }}
                        />
                        Modify User Access
                    </Typography>

                    {/* Select user and device access form goes here */}
                    <FormControl sx={{ mt: 2 }}>
                        <InputLabel id="select-user-label">
                            Select User
                        </InputLabel>
                        <Select
                            labelId="select-user-label"
                            value={userForAccess || ''}
                            label="Select User"
                            onChange={(e) => setUserForAccess(e.target.value)}
                        >
                            {users?.map((user: UserInfo) => (
                                <MenuItem
                                    key={user.username}
                                    value={user.username}
                                >
                                    {user.username}
                                </MenuItem>
                            ))}
                        </Select>
                    </FormControl>
                    <TextField
                        label="Device ID"
                        onChange={(e) => setDevice(e.target.value)}
                        value={device}
                    />
                    <FormControl>
                        <InputLabel id="select-access-level-label">
                            Access Level
                        </InputLabel>
                        <Select
                            labelId="select-access-level-label"
                            value={accessLevel}
                            label="Access Level"
                            onChange={(e) =>
                                setAccessLevel(
                                    e.target.value.toLowerCase() as AccessLevel
                                )
                            }
                        >
                            <MenuItem value={AccessLevel.OWNER}>OWNER</MenuItem>
                            <MenuItem value={AccessLevel.VIEWER}>
                                VIEWER
                            </MenuItem>
                            <MenuItem value={AccessLevel.ADMIN}>ADMIN</MenuItem>
                            <MenuItem value={AccessLevel.NONE}>NONE</MenuItem>
                        </Select>
                    </FormControl>
                    <Button
                        variant="contained"
                        sx={{ mt: 3 }}
                        onClick={() => {
                            if (userForAccess) {
                                addContentAccessToUser(
                                    userForAccess,
                                    device,
                                    accessLevel
                                );
                                setOpen(false);
                            }
                        }}
                    >
                        Save Changes
                    </Button>
                </Stack>
            </ModalWithCloseButton>

            <ModalWithCloseButton
                open={openSensor}
                onClose={() => setOpenSensor(false)}
                fitContent
            >
                <Stack spacing={2} sx={{ width: 400, p: 3 }}>
                    <Typography variant="h6" align="center" marginY={2}>
                        <VerifiedUserRounded
                            sx={{ mr: 1, verticalAlign: 'middle' }}
                        />
                        Add Sensor Access
                    </Typography>

                    {/* Select user and device access form goes here */}
                    <FormControl sx={{ mt: 2 }}>
                        <InputLabel id="select-user-label">
                            Select User
                        </InputLabel>
                        <Select
                            labelId="select-user-label"
                            value={userForAccess || ''}
                            label="Select User"
                            onChange={(e) => setUserForAccess(e.target.value)}
                        >
                            {users?.map((user: UserInfo) => (
                                <MenuItem
                                    key={user.username}
                                    value={user.username}
                                >
                                    {user.username}
                                </MenuItem>
                            ))}
                        </Select>
                    </FormControl>
                    <TextField
                        label="Device ID"
                        onChange={(e) => setSensorDeviceId(e.target.value)}
                        value={sensorDeviceId}
                    />
                    <TextField
                        label="Device Nickname"
                        onChange={(e) => setDeviceNickname(e.target.value)}
                        value={deviceNickname}
                    />
                    <TextField
                        label="Sensor Type"
                        defaultValue="biometrics"
                        onChange={(e) => setSensorType(e.target.value)}
                        value={sensorType}
                    />
                    <TextField
                        helperText="For camera only, leave blank for biometrics"
                        label="Sensor Secret"
                        defaultValue=""
                        onChange={(e) => setSensorSecret(e.target.value)}
                        value={sensorSecret}
                    />
                    <Button
                        variant="contained"
                        sx={{ mt: 3 }}
                        onClick={() => {
                            if (userForAccess) {
                                addSensorAccessToUser(
                                    sensorDeviceId,
                                    sensorType,
                                    sensorSecret,
                                    deviceNickname,
                                    userForAccess
                                );
                                setOpenSensor(false);
                            }
                        }}
                    >
                        Save Changes
                    </Button>
                </Stack>
            </ModalWithCloseButton>
        </Stack>
    );
};

export default Admin;

import {
    AddRounded,
    CameraAltRounded,
    PersonRounded,
    VerifiedUserRounded,
} from '@mui/icons-material';
import {
    Button,
    Divider,
    FormControl,
    InputLabel,
    MenuItem,
    Select,
    Stack,
    TextField,
    Typography,
} from '@mui/material';
import { changeUserAccess, getUsers } from 'apis/auth';
import ModalWithCloseButton from 'components/ModalWithCloseButton';
import React from 'react';
import { useCookies } from 'react-cookie';
import { useNavigate } from 'react-router';
import { useAppSelector } from 'reducers/hooks';
import useSWR from 'swr';
import { AccessLevel, DeviceAccess, UserInfo } from 'types/auth';

const Admin = () => {
    const { isAuthenticated } = useAppSelector((state) => state.auth);
    const [cookies] = useCookies(['token']);
    const [open, setOpen] = React.useState(false);
    const [userForAccess, setUserForAccess] = React.useState<string | null>(
        null
    );
    const [deviceId, setDeviceId] = React.useState<string>('');
    const [accessLevel, setAccessLevel] = React.useState<AccessLevel>(
        AccessLevel.NONE
    );
    const navigate = useNavigate();
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

    const addDeviceAccessToUser = (
        username: string,
        deviceId: string,
        accessLevel: AccessLevel
    ) => {
        changeUserAccess(cookies.token, username, deviceId, accessLevel);
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
                        <Button
                            variant="outlined"
                            sx={{ mt: 2, textTransform: 'none' }}
                            onClick={() => {
                                setUserForAccess(user.username);
                                setDeviceId('');
                                setAccessLevel(AccessLevel.NONE);
                                setOpen(true);
                            }}
                        >
                            Add Device Access <AddRounded sx={{ ml: 1 }} />
                        </Button>
                    </Stack>
                    <Stack
                        alignItems="flex-start"
                        spacing={1}
                        sx={{ width: '100%', mt: 1 }}
                    >
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
                                            setDeviceId(device.deviceId);
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
                    </Stack>
                </React.Fragment>
            ))}
            <ModalWithCloseButton open={open} onClose={() => setOpen(false)}>
                <Typography variant="h6" align="center" marginTop={2}>
                    <VerifiedUserRounded
                        sx={{ mr: 1, verticalAlign: 'middle' }}
                    />
                    Modify User Access
                </Typography>
                {/* Select user and device access form goes here */}
                <FormControl fullWidth sx={{ mt: 2 }}>
                    <InputLabel id="select-user-label">Select User</InputLabel>
                    <Select
                        labelId="select-user-label"
                        value={userForAccess || ''}
                        label="Select User"
                        onChange={(e) => setUserForAccess(e.target.value)}
                    >
                        {users?.map((user: UserInfo) => (
                            <MenuItem key={user.username} value={user.username}>
                                {user.username}
                            </MenuItem>
                        ))}
                    </Select>
                </FormControl>
                <TextField
                    label="Device ID"
                    sx={{ mt: 2 }}
                    onChange={(e) => setDeviceId(e.target.value)}
                    value={deviceId}
                />
                <FormControl fullWidth sx={{ mt: 2 }}>
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
                        <MenuItem value={AccessLevel.VIEWER}>VIEWER</MenuItem>
                        <MenuItem value={AccessLevel.ADMIN}>ADMIN</MenuItem>
                        <MenuItem value={AccessLevel.NONE}>NONE</MenuItem>
                    </Select>
                </FormControl>
                <Button
                    variant="contained"
                    sx={{ mt: 3 }}
                    onClick={() => {
                        if (userForAccess) {
                            addDeviceAccessToUser(
                                userForAccess,
                                deviceId,
                                accessLevel
                            );
                            setOpen(false);
                        }
                    }}
                >
                    Save Changes
                </Button>
            </ModalWithCloseButton>
        </Stack>
    );
};
export default Admin;

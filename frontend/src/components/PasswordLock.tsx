import React, { useEffect, useState } from 'react';
import { useCookies } from 'react-cookie';
import { useNavigate, useSearchParams } from 'react-router';
import { verifyTokenRequest } from '../apis/auth';
import {
    AppBar,
    Box,
    Button,
    Chip,
    Container,
    Drawer,
    IconButton,
    Popover,
    Stack,
    Toolbar,
    Tooltip,
    Typography,
} from '@mui/material';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import { login, logout } from 'reducers/auth';
import axios from 'axios';
import { useSWRConfig } from 'swr';
import DeletedImages from './DeletedImages';
import {
    AdminPanelSettingsRounded,
    CheckCircleOutlineRounded,
    FaceRounded,
    HomeRounded,
    LoginRounded,
    LogoutRounded,
    MonitorHeartRounded,
    SearchRounded,
    UploadRounded,
} from '@mui/icons-material';
import DeviceSelect from '../pages/DeviceSelect';
import DRESSettings from './DRESSettings';

const DRESWidget = () => {
    const [anchor, setAnchor] = useState<HTMLElement | null>(null);
    const { sessionId, evaluationId } = useAppSelector((s) => s.dres);
    const isLoggedIn = !!sessionId;
    return (
        <>
            {isLoggedIn ? (
                <Chip
                    icon={<CheckCircleOutlineRounded />}
                    label={evaluationId ? 'DRES' : 'DRES (no eval)'}
                    color="success"
                    size="small"
                    onClick={(e) => setAnchor(e.currentTarget)}
                    sx={{ cursor: 'pointer', ml: 1 }}
                />
            ) : (
                <Button
                    size="small"
                    startIcon={<LoginRounded />}
                    onClick={(e) => setAnchor(e.currentTarget)}
                    sx={{ ml: 1 }}
                >
                    DRES
                </Button>
            )}
            <Popover
                open={Boolean(anchor)}
                anchorEl={anchor}
                onClose={() => setAnchor(null)}
                anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
                transformOrigin={{ vertical: 'top', horizontal: 'right' }}
                slotProps={{ paper: { sx: { p: 2, minWidth: 320 } } }}
            >
                <Typography variant="subtitle2" fontWeight="bold" mb={1}>
                    DRES Competition
                </Typography>
                <DRESSettings />
            </Popover>
        </>
    );
};

const PasswordLock = ({ children }: { children: React.ReactNode }) => {
    const navigate = useNavigate();
    const [searchParams, _] = useSearchParams();
    const { isAuthenticated, deviceId } = useAppSelector((state) => state.auth);
    const dispatch = useAppDispatch();
    const [cookies, _setCookies, removeCookies] = useCookies(['token']);

    const { mutate } = useSWRConfig();

    const clearAuthentication = () => {
        console.log('Clearing authentication');
        dispatch(logout());
        removeCookies('token', { path: '/' });
        axios.defaults.headers.common['Authorization'] = '';
        mutate(
            (_: any) => true,
            undefined, // update cache data to `undefined`
            { revalidate: false } // do not revalidate
        );
        navigate('/login');
    };

    useEffect(() => {
        if (cookies.token) {
            verifyTokenRequest(cookies.token)
                .then((response) => {
                    if (response.data.success) {
                        dispatch(
                            login({
                                username: response.data.username,
                                devices: response.data.devices,
                                sensors: response.data.sensors,
                            })
                        );
                        axios.defaults.headers.common['Authorization'] =
                            `Bearer ${cookies.token}`;
                    } else {
                        clearAuthentication();
                    }
                })
                .catch((error) => {
                    console.error('There was an error verifying token!', error);
                    clearAuthentication();
                });
        } else {
            clearAuthentication();
        }
    }, []);

    if (isAuthenticated) {
        return (
            <>
                <AppBar
                    position="sticky"
                    color="transparent"
                    elevation={0}
                    sx={{
                        zIndex: (theme) => theme.zIndex.drawer + 1,
                        borderBottom: '1px solid',
                        borderColor: 'divider',
                        backdropFilter: 'blur(8px)',
                        ml: 4,
                        mr: 4,
                    }}
                >
                    <Toolbar>
                        <Typography
                            variant="h6"
                            color="primary"
                            fontWeight="bold"
                            sx={{ mr: 2, whiteSpace: 'nowrap' }}
                        >
                            SelfHealth
                        </Typography>
                        <Box sx={{ flex: 1 }} />
                        <DeviceSelect />
                        <DRESWidget />
                    </Toolbar>
                </AppBar>
                <Drawer
                    variant="permanent"
                    open
                    sx={{ zIndex: 2200 }}
                >
                    <Stack spacing={2} alignItems="center" mt={2}>
                        <Tooltip title="Home">
                            <IconButton
                                size="large"
                                color="secondary"
                                // onClick={() => navigate(`/${deviceId ? `?device=${deviceId}` : ''}`)}
                                onClick={() => {
                                    // keep device and date
                                    const date = searchParams.get('date');
                                    const device = searchParams.get('device');
                                    navigate(`/?${device ? `device=${device}&` : ''}${date ? `date=${date}` : ''}`);
                                }}
                            >
                                <HomeRounded />
                            </IconButton>
                        </Tooltip>
                        <Tooltip title="Biometrics">
                            <IconButton
                                size="large"
                                color="secondary"
                                onClick={() => {
                                    // keep device and date
                                    const date = searchParams.get('date');
                                    const device = searchParams.get('device');
                                    navigate(`/biometrics?${device ? `device=${device}&` : ''}${date ? `date=${date}` : ''}`);
                                }}
                            >
                                <MonitorHeartRounded />
                            </IconButton>
                        </Tooltip>
                        <Tooltip title="Deleted Images">
                            <DeletedImages />
                        </Tooltip>
                        <Tooltip title="Search Images">
                            <IconButton
                                size="large"
                                color="secondary"
                                onClick={() => navigate(`/search?mode=text${deviceId ? `&device=${deviceId}` : ''}`)}
                            >
                                <SearchRounded />
                            </IconButton>
                        </Tooltip>
                        <Tooltip title="People">
                            <IconButton
                                size="large"
                                color="secondary"
                                onClick={() => navigate(`/faces${deviceId ? `?device=${deviceId}` : ''}`)}
                            >
                                <FaceRounded />
                            </IconButton>
                        </Tooltip>
                        <Tooltip title="Admin Panel">
                            <IconButton
                                size="large"
                                color="secondary"
                                onClick={() => navigate('/admin')}
                            >
                                <AdminPanelSettingsRounded />
                            </IconButton>
                        </Tooltip>
                        <Tooltip title="Upload Images/Videos">
                            <IconButton
                                size="large"
                                color="secondary"
                                onClick={() => navigate(`/upload${deviceId ? `?device=${deviceId}` : ''}`)}
                            >
                                <UploadRounded />
                            </IconButton>
                        </Tooltip>
                        {/* <Tooltip title="Upload Status"> */}
                        {/*     <IconButton */}
                        {/*         color="secondary" */}
                        {/*         onClick={() => navigate('/status')} */}
                        {/*         sx={{ marginTop: '16px' }} */}
                        {/*     > */}
                        {/*         <RotateLeftRounded /> */}
                        {/*     </IconButton> */}
                        {/* </Tooltip> */}
                        <Tooltip title="Logout">
                            <IconButton
                                size="large"
                                color="secondary"
                                onClick={clearAuthentication}
                            >
                                <LogoutRounded />
                            </IconButton>
                        </Tooltip>
                    </Stack>
                </Drawer>
                {/* Main Content */}
                <Container maxWidth={false} sx={{ ml: 3, mt: 4 }}>
                    {children}
                </Container>
            </>
        );
    }
    return <></>;
};

export default PasswordLock;

import React, { useEffect } from 'react';
import { useCookies } from 'react-cookie';
import { useNavigate, useSearchParams } from 'react-router';
import { verifyTokenRequest } from '../apis/auth';
import {
    AppBar,
    Box,
    Button,
    Container,
    Drawer,
    IconButton,
    Stack,
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
    FaceRounded,
    HomeRounded,
    LogoutOutlined,
    LogoutRounded,
    MonitorHeartRounded,
    RotateLeftRounded,
    SearchRounded,
    UploadRounded,
} from '@mui/icons-material';

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
                <AppBar position="static" color="transparent" elevation={0} sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}>
                    <Typography
                        variant="h5"
                        margin={2}
                        pl={4}
                        color="primary"
                        fontWeight="bold"
                    >
                        SelfHealth
                    </Typography>
                </AppBar>
                <Drawer
                    variant="permanent"
                    open
                    sx={{ zIndex: (theme) => theme.zIndex.appBar - 1 }}
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

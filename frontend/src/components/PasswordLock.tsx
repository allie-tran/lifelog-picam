import React, { useEffect } from 'react';
import { useCookies } from 'react-cookie';
import { useNavigate } from 'react-router';
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
    RotateLeftRounded,
    SearchRounded,
    UploadRounded,
} from '@mui/icons-material';

const PasswordLock = ({ children }: { children: React.ReactNode }) => {
    const navigate = useNavigate();
    const { isAuthenticated } = useAppSelector((state) => state.auth);
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
                <AppBar position="static" color="transparent" elevation={0}>
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
                                onClick={() => navigate('/')}
                            >
                                <HomeRounded />
                            </IconButton>
                        </Tooltip>
                        <Tooltip title="Deleted Images">
                            <DeletedImages />
                        </Tooltip>
                        <Tooltip title="Search Images">
                            <IconButton
                                size="large"
                                color="secondary"
                                onClick={() => navigate('/search?mode=text')}
                            >
                                <SearchRounded />
                            </IconButton>
                        </Tooltip>
                        <Tooltip title="People">
                            <IconButton
                                size="large"
                                color="secondary"
                                onClick={() => navigate('/faces')}
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
                                onClick={() => navigate('/upload')}
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

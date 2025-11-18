import React, { useEffect } from 'react';
import { useCookies } from 'react-cookie';
import { useNavigate } from 'react-router';
import { verifyTokenRequest } from '../apis/auth';
import { AppBar, Button, Container, Stack } from '@mui/material';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import { login, logout } from 'reducers/auth';
import axios from 'axios';
import { useSWRConfig } from 'swr';

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
                <AppBar
                    sx={{ position: 'fixed', backgroundColor: 'primary.main' }}
                    elevation={0}
                >
                    <Stack
                        direction="row"
                        justifyContent="flex-end"
                        alignItems="center"
                    >
                        <Button
                            onClick={clearAuthentication}
                            sx={{
                                color: 'primary.contrastText',
                                fontWeight: 'bold',
                            }}
                        >
                            Logout
                        </Button>
                    </Stack>
                </AppBar>
                <Container sx={{ pt: 8 }}>{children}</Container>
            </>
        );
    }
    return <></>;
};

export default PasswordLock;

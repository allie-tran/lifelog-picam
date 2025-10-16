import React, { useEffect } from 'react';
import { useCookies } from 'react-cookie';
import { useNavigate } from 'react-router';
import { verifyTokenRequest } from '../apis/auth';
import { AppBar, Button, Container, Stack } from '@mui/material';

const PasswordLock = ({ children }: { children: React.ReactNode }) => {
    const navigate = useNavigate();
    const [isAuthenticated, setIsAuthenticated] = React.useState(false);
    const [cookies, _setCookies, removeCookies] = useCookies(['token']);

    const clearAuthentication = () => {
        removeCookies('token', { path: '/' });
        setIsAuthenticated(false);
        navigate('/login');
    };

    useEffect(() => {
        if (cookies.token) {
            verifyTokenRequest(cookies.token)
                .then((response) => {
                    if (response.data.success) {
                        setIsAuthenticated(true);
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
                <AppBar sx={{ position: 'fixed' }} elevation={0}>
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

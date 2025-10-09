import { Button, Stack, TextField, Typography } from '@mui/material';
import { useEffect, useState } from 'react';
import { loginRequest } from '../apis/auth';
import { parseErrorResponse } from '../utils/misc';
import { useCookies } from 'react-cookie';
import { Link, useNavigate } from 'react-router';

const Login = () => {
    const navigate = useNavigate();
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [cookies, setCookie, removeCookie] = useCookies(['token']);

    useEffect(() => {
        if (cookies.token) {
            // If token exists, redirect to main page
            navigate('/');
        }
    }, []);

    const handleRegister = () => {
        loginRequest(username, password)
            .then((response: any) => {
                console.log(response);
                const token = response.data.token;
                // Save to cookie
                setCookie('token', token, { path: '/', maxAge: 3600 });
                navigate('/');
            })
            .catch((error: any) => {
                console.error('There was an error loging in!', error);
                alert(parseErrorResponse(error.response));
                // remove invalid token
                removeCookie('token', { path: '/' });
            });
    };

    return (
        <>
            <Typography variant="h4" align="center" marginTop={4}>
                Login
            </Typography>
            <Stack spacing={2} alignItems="center" marginTop={4}>
                <TextField
                    label="Username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    sx={{ width: '300px' }}
                />
                <TextField
                    label="Password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    sx={{ width: '300px' }}
                />
                <Button
                    variant="contained"
                    onClick={handleRegister}
                >
                    Login
                </Button>
                <Typography variant="body2" sx={{ mt: 2 }}>
                    Don't have an account? Register <Link to="/register">here</Link>.
                </Typography>
            </Stack>
        </>
    );
};
export default Login;

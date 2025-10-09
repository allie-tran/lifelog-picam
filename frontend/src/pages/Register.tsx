import { useState } from 'react';
import { createUserRequest } from '../apis/auth';
import { Button, Stack, TextField, Typography } from '@mui/material';
import { parseErrorResponse } from '../utils/misc';
import { Link, Navigate, useNavigate } from 'react-router';

const Register = () => {
    const navigate = useNavigate();
    const [username, setUsername] = useState('');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [adminCode, setAdminCode] = useState('');

    const handleRegister = () => {
        createUserRequest(username, password, email, adminCode)
            .then((response: any) => {
                if (response.data.success) {
                    alert('User registered successfully');
                } else {
                    alert('Registration failed: ' + response.data.message);
                }
                // redirect to login page after successful registration
                navigate('/login');
            })
            .catch((error: any) => {
                console.error('There was an error registering!', error);
                const message = parseErrorResponse(error.response);
                if (message === 'User already exists') {
                    navigate('/login');
                }
            });
    };

    return (
        <>
            <Typography variant="h4" align="center" marginTop={4}>
                Register New User
            </Typography>
            <Stack spacing={2} alignItems="center" marginTop={4}>
                <TextField
                    label="Username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    sx={{ width: '300px' }}
                />
                <TextField
                    label="Email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    sx={{ width: '300px' }}
                />
                <TextField
                    label="Password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    sx={{ width: '300px' }}
                />
                <TextField
                    label="Admin Code"
                    type="password"
                    value={adminCode}
                    onChange={(e) => setAdminCode(e.target.value)}
                    sx={{ width: '300px' }}
                />
                <Typography variant="body2">
                    Request an admin code by emailing <Link to="mailto:allie.tran@dcu.ie">allie.tran@dcu.ie</Link>.
                </Typography>
                <Stack direction="row" spacing={2}>
                    <Button
                        variant="contained"
                        onClick={handleRegister}
                        disabled={!username || !email || !password || !adminCode}
                    >
                        Register
                    </Button>
                </Stack>
                <Typography variant="body2">
                    Already have an account? Login <Link to="/login">here</Link>.
                </Typography>

            </Stack>
        </>
    );
};
export default Register;

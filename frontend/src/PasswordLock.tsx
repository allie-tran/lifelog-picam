import {
    Button,
    Stack,
    TextField,
    Typography
} from '@mui/material';
import axios from 'axios';
import React from 'react';
import './App.css';
import { BACKEND_URL } from './constants';
import ModalWithCloseButton from './ModalWithCloseButton';

const PasswordLock = ({ children }: { children: React.ReactNode }) => {
    const [password, setPassword] = React.useState('');
    const [isAuthenticated, setIsAuthenticated] = React.useState(false);

    const handlePasswordSubmit = () => {
        const url = `${BACKEND_URL}/login?password=${encodeURIComponent(password)}`;
        axios
            .get(url)
            .then((response) => {
                if (response.data.success) {
                    setIsAuthenticated(true);
                }
            })
            .catch((error) => {
                console.error('There was an error logging in!', error);
                alert('Incorrect password. Please try again.');
            });
    };

    if (isAuthenticated) {
        return <>{children}</>;
    }

    return (
        <ModalWithCloseButton open={true} onClose={() => {}}>
            <Stack spacing={2} alignItems="center">
                <Typography variant="h6">Enter Password to Access</Typography>
                <TextField
                    type="password"
                    label="Password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    sx={{ width: '300px' }}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            handlePasswordSubmit();
                        }
                    }}
                />
                <Button variant="contained" onClick={handlePasswordSubmit}>
                    Submit
                </Button>
            </Stack>
        </ModalWithCloseButton>
    );
};

export default PasswordLock;

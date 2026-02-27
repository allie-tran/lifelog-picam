import { ThemeProvider } from '@emotion/react';
import {
    Box,
    Container,
    createTheme,
    CssBaseline,
    responsiveFontSizes,
} from '@mui/material';
import { LocalizationProvider } from '@mui/x-date-pickers';
import { AdapterDayjs } from '@mui/x-date-pickers/AdapterDayjs';
import Login from 'pages/Login';
import MainPage from 'pages/MainPage';
import Register from 'pages/Register';
import SearchPage from 'pages/SearchPage';
import SimilarImages from 'pages/SimilarImagesPage';
import { CookiesProvider } from 'react-cookie';
import { BrowserRouter, Route, Routes } from 'react-router';
import './App.css';
import PasswordLock from './components/PasswordLock';

import FeedbackComponents from 'components/FeedbackComponents';
import dayjs from 'dayjs';
import Admin from 'pages/Admin';
import FaceIntelligence from 'pages/Faces';
import { ProcessingStatusPage } from 'pages/ProcessingStatusPage';
import { UploadPage } from 'pages/UploadPage';
import { Provider } from 'react-redux';
import { store } from 'reducers/store';
var localizedFormat = require('dayjs/plugin/localizedFormat');

const activityTrackerTheme = createTheme({
    palette: {
        mode: 'light',
        primary: {
            main: '#FF9E7D', // Warm Sunset
            contrastText: '#fff',
        },
        secondary: {
            main: '#16A299', // Bright Teal
        },
        success: {
            main: '#A8E6CF', // Soft Mint
        },
        background: {
            default: '#FDFCF0',
            paper: 'rgba(255, 255, 255, 0.85)', // Slightly translucent for glassmorphism effect
        },
        text: {
            primary: '#2D3436',
            secondary: '#636E72',
        },
    },
    typography: {
        fontFamily: '"Inter", "Roboto", "Helvetica", "Arial", sans-serif',
        h1: {
            fontSize: '2rem',
            fontWeight: 700,
            color: '#8E44AD', // Primary purple for the main title
            textAlign: 'center',
        },
        h2: {
            fontSize: '1.125rem',
            fontWeight: 600,
            color: '#2D3436',
        },
        body1: {
            fontSize: '0.875rem',
            color: '#2D3436',
        },
        button: {
            textTransform: 'none',
            fontWeight: 600,
        },
    },
    shape: {
        borderRadius: 12, // Increased radius for a softer, modern look
    },
    components: {
        MuiOutlinedInput: {
            styleOverrides: {
                root: {
                    backgroundColor: 'background.paper',
                    '& .MuiOutlinedInput-notchedOutline': {
                        borderColor: '#DFE6E9', // Subtle border for inputs
                    },
                    '&:hover .MuiOutlinedInput-notchedOutline': {
                        borderColor: '#8E44AD',
                    },
                },
            },
        },
        MuiButton: {
            styleOverrides: {
                root: {
                    textTransform: 'none',
                },
                outlinedPrimary: {
                    '&:hover': {
                        borderWidth: '1px',
                        borderColor: 'secondary.main',
                    },
                },
                containedPrimary: {
                    '&:hover': {
                        backgroundColor: 'secondary.main',
                        boxShadow: '0px 4px 12px rgba(142, 68, 173, 0.2)',
                    },
                },
            },
        },
        MuiCard: {
            styleOverrides: {
                root: {
                    border: 'none',
                    boxShadow: '0px 2px 8px rgba(0, 0, 0, 0.05)', // Soft shadow instead of borders
                    '&:hover': {
                        boxShadow: '0px 4px 16px rgba(0, 0, 0, 0.08)',
                    },
                },
            },
        },
        MuiListItemButton: {
            styleOverrides: {
                root: {
                    borderRadius: 8,
                    marginBottom: 4,
                    '&.Mui-selected': {
                        '&:hover': {},
                        '& .MuiListItemIcon-root': {},
                    },
                },
            },
        },
    },
});

const theme = responsiveFontSizes(activityTrackerTheme);
dayjs.extend(localizedFormat);

const App = () => {
    return (
        <Provider store={store}>
            <CookiesProvider>
                <ThemeProvider theme={theme}>
                    <CssBaseline />
                    <Box
                        sx={{
                            display: 'flex',
                            minHeight: '100vh',
                            position: 'relative',
                            overflow: 'hidden',
                            // Dynamic Gradient Mesh Background
                            background: `
                                radial-gradient(at 0% 0%, rgba(255, 158, 125, 0.15) 0px, transparent 50%),
                                radial-gradient(at 100% 0%, rgba(78, 205, 196, 0.15) 0px, transparent 50%),
                                radial-gradient(at 100% 100%, rgba(168, 230, 207, 0.2) 0px, transparent 50%),
                                radial-gradient(at 0% 100%, rgba(255, 158, 125, 0.1) 0px, transparent 50%),
                                #FDFCF0
                            `,
                        }}
                    >
                        <LocalizationProvider dateAdapter={AdapterDayjs}>
                            <FeedbackComponents />
                            <Container
                                maxWidth={false}
                                sx={{ marginTop: '0px', marginBottom: '40px' }}
                            >
                                <BrowserRouter basename={'/selfhealth/'}>
                                    <Routes>
                                        <Route
                                            path="/"
                                            element=<PasswordLock>
                                                <MainPage />
                                            </PasswordLock>
                                        />
                                        <Route
                                            path="/register"
                                            element=<Register />
                                        />
                                        <Route
                                            path="/login"
                                            element=<Login />
                                        />
                                        <Route
                                            path="/search"
                                            element=<PasswordLock>
                                                <SearchPage />
                                            </PasswordLock>
                                        />
                                        <Route
                                            path="/similar"
                                            element=<PasswordLock>
                                                <SimilarImages />
                                            </PasswordLock>
                                        />
                                        <Route
                                            path="/admin"
                                            element=<PasswordLock>
                                                <Admin />
                                            </PasswordLock>
                                        />
                                        <Route
                                            path="/upload"
                                            element=<PasswordLock>
                                                <UploadPage />
                                            </PasswordLock>
                                        />
                                        <Route
                                            path="/status/:jobId"
                                            element=<PasswordLock>
                                                <ProcessingStatusPage />
                                            </PasswordLock>
                                        />
                                        <Route
                                            path="/faces"
                                            element=<PasswordLock>
                                                <FaceIntelligence />
                                            </PasswordLock>
                                        />
                                    </Routes>
                                </BrowserRouter>
                            </Container>
                        </LocalizationProvider>
                    </Box>
                </ThemeProvider>
            </CookiesProvider>
        </Provider>
    );
};

export default App;

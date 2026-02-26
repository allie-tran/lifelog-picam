import { ThemeProvider } from '@emotion/react';
import {
    Container,
    createTheme,
    CssBaseline,
    responsiveFontSizes
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

/**
 * Material UI Theme configuration matching the ActivityTracker aesthetic.
 * Incorporates the dark purple palette, Inter typography, and rounded components.
 */
const activityTrackerTheme = createTheme({
    palette: {
        mode: 'dark',
        primary: {
            main: '#b085f5', // The light purple accent
            contrastText: '#000000',
        },
        secondary: {
            main: '#FF79C6',
        },
        background: {
            default: '#2d2d3d', // Main background
            paper: '#36364a', // Surface/Card background
        },
        text: {
            primary: '#F8F8F2',
            secondary: '#BFBFC4',
        },
        error: {
            main: '#FF5555',
        },
        success: {
            main: '#50FA7B',
        },
        divider: '#6272A4',
    },
    typography: {
        fontFamily: '"Inter", "Roboto", "Helvetica", "Arial", sans-serif',
        h1: {
            fontSize: '2rem',
            fontWeight: 700,
            color: '#b085f5',
            textAlign: 'center',
        },
        h2: {
            fontSize: '1.125rem',
            fontWeight: 600,
        },
        body1: {
            fontSize: '0.875rem',
        },
        button: {
            textTransform: 'none',
            fontWeight: 600,
        },
    },
    shape: {
        borderRadius: 8,
    },
    components: {
        // Styling the search inputs to match the custom border/bg
        MuiOutlinedInput: {
            styleOverrides: {
                root: {
                    '& .MuiOutlinedInput-notchedOutline': {
                        borderColor: 'rgba(255, 255, 255, 0.1)',
                    },
                    '&:hover .MuiOutlinedInput-notchedOutline': {
                        borderColor: '#b085f5',
                    },
                },
            },
        },
        // Styling buttons to match the outlined purple look
        MuiButton: {
            styleOverrides: {
                outlinedPrimary: {
                    borderWidth: '1px',
                    '&:hover': {
                        borderWidth: '1px',
                        backgroundColor: '#b085f5',
                        color: '#000000',
                    },
                },
                containedPrimary: {
                    backgroundColor: '#b085f5',
                    color: '#000000',
                    '&:hover': {
                        backgroundColor: '#9969f3',
                    },
                },
            },
        },
        // Sidebar / Paper items
        MuiCard: {
            styleOverrides: {
                root: {
                    borderColor: 'rgba(255, 255, 255, 0.1)',
                    '&:hover': {
                        borderColor: '#b085f5',
                    },
                },
            },
        },
        // List styling for the "Sort By" pills
        MuiListItemButton: {
            styleOverrides: {
                root: {
                    borderRadius: 6,
                    marginBottom: 4,
                    '&.Mui-selected': {
                        backgroundColor: '#b085f5',
                        color: '#000000',
                        '&:hover': {
                            backgroundColor: '#9969f3',
                        },
                        '& .MuiListItemIcon-root': {
                            color: '#000000',
                        },
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
                                    <Route path="/login" element=<Login /> />
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
                </ThemeProvider>
            </CookiesProvider>
        </Provider>
    );
};

export default App;

import { ThemeProvider } from '@emotion/react';
import { ArrowLeftRounded } from '@mui/icons-material';
import {
    AppBar,
    Container,
    createTheme,
    CssBaseline,
    responsiveFontSizes,
    Typography,
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

import { Provider } from 'react-redux';
import { store } from 'reducers/store';
import dayjs from 'dayjs';
import FeedbackComponents from 'components/FeedbackComponents';
var localizedFormat = require('dayjs/plugin/localizedFormat');

let theme = createTheme({
    palette: {
        primary: {
            main: '#BD93F9',
        },
        secondary: {
            main: '#FF79C6',
        },
        error: {
            main: '#FF5555',
        },
        success: {
            main: '#50FA7B',
        },
        mode: 'dark',
        background: {
            default: '#282A36',
            paper: '#343746',
        },
        divider: '#6272A4',
        text: {
            primary: '#F8F8F2',
            secondary: '#BFBFC4',
        },
    },
    typography: {
        fontFamily: 'Roboto, Arial, sans-serif',
    },
});
theme = responsiveFontSizes(theme);
dayjs.extend(localizedFormat);

const App = () => {
    return (
        <Provider store={store}>
            <CookiesProvider>
                <ThemeProvider theme={theme}>
                    <CssBaseline />
                    <LocalizationProvider dateAdapter={AdapterDayjs}>
                        <AppBar
                            sx={{
                                position: 'fixed',
                                backgroundColor: 'transparent',
                                zIndex: 1101,
                            }}
                            elevation={0}
                        >
                            <Typography
                                margin={1}
                                fontWeight="bold"
                                onClick={() => {
                                    window.location.href = '/omi/';
                                }}
                                sx={{ cursor: 'pointer', color: 'primary.contrastText' }}
                            >
                                <ArrowLeftRounded
                                    sx={{ verticalAlign: 'middle', mt: '-4px' }}
                                />
                                Back to Home
                            </Typography>
                        </AppBar>
                        <FeedbackComponents />
                        <Container
                            sx={{ marginTop: '0px', marginBottom: '40px' }}
                        >
                            <BrowserRouter basename={'/omi'}>
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

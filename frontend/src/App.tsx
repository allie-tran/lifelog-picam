import { ThemeProvider } from '@emotion/react';
import { ArrowLeftRounded } from '@mui/icons-material';
import {
    AppBar,
    Container,
    createTheme,
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
var localizedFormat = require('dayjs/plugin/localizedFormat');

let theme = createTheme({
    palette: {
        primary: {
            main: '#BD93F9',
        },
        secondary: {
            main: '#dc004e',
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
                                sx={{ cursor: 'pointer' }}
                            >
                                <ArrowLeftRounded
                                    sx={{ verticalAlign: 'middle', mt: '-4px' }}
                                />
                                Back to Home
                            </Typography>
                        </AppBar>
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

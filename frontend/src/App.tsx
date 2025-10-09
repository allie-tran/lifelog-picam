import { ThemeProvider } from '@emotion/react';
import { Container, createTheme, responsiveFontSizes } from '@mui/material';
import { LocalizationProvider } from '@mui/x-date-pickers';
import { AdapterDayjs } from '@mui/x-date-pickers/AdapterDayjs';
import { BrowserRouter, Route, Routes } from 'react-router';
import './App.css';
import PasswordLock from './components/PasswordLock';
import MainPage from './pages/MainPage';
import Register from './pages/Register';
import Login from './pages/Login';
import { CookiesProvider } from 'react-cookie';
// import { createStore } from 'redux';
// import { Provider } from 'react-redux';
// const store = createStore(rootReducer);

let theme = createTheme({
    palette: {
        primary: {
            main: '#BD93F9',
        },
        secondary: {
            main: '#dc004e',
        },
    },
});
theme = responsiveFontSizes(theme);

const App = () => {
    return (
        <CookiesProvider>
            <ThemeProvider theme={theme}>
                <LocalizationProvider dateAdapter={AdapterDayjs}>
                    <Container>
                        <BrowserRouter>
                            <Routes>
                                <Route
                                    path="/"
                                    element=<PasswordLock>
                                        <MainPage />
                                    </PasswordLock>
                                />
                                <Route path="/register" element=<Register /> />
                                <Route path="/login" element=<Login /> />
                            </Routes>
                        </BrowserRouter>
                    </Container>
                </LocalizationProvider>
            </ThemeProvider>
        </CookiesProvider>
    );
};

export default App;

import { ThemeProvider } from '@emotion/react';
import { createTheme, responsiveFontSizes } from '@mui/material';
import { LocalizationProvider } from '@mui/x-date-pickers';
import { AdapterDayjs } from '@mui/x-date-pickers/AdapterDayjs';
import './App.css';
import PasswordLock from './PasswordLock';
import MainPage from './MainPage';

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
        <ThemeProvider theme={theme}>
            <PasswordLock>
                <LocalizationProvider dateAdapter={AdapterDayjs}>
                    <MainPage />
                </LocalizationProvider>
            </PasswordLock>
        </ThemeProvider>
    );
};

export default App;

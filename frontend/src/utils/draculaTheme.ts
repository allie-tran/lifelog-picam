// draculaMaterialTheme.ts
import { createTheme, alpha } from '@mui/material/styles';

const dracula = {
    background: '#282a36',
    surface: '#2e303e', // slightly lifted surface from base
    surfaceAlt: '#343746',
    line: '#9999a8',
    foreground: '#f8f8f2',

    comment: '#6272a4',
    cyan: '#8be9fd',
    green: '#50fa7b',
    orange: '#ffb86c',
    pink: '#ff79c6',
    purple: '#bd93f9',
    red: '#ff5555',
    yellow: '#f1fa8c',
};

export const draculaDarkTheme = createTheme({
    palette: {
        mode: 'dark',
        primary: {
            main: dracula.purple,
            light: '#cfb6ff',
            dark: '#8e62d6',
            contrastText: dracula.background,
        },
        secondary: {
            main: dracula.cyan,
            light: '#bdf6ff',
            dark: '#5bd3e5',
            contrastText: '#0b0c10',
        },
        error: { main: dracula.red },
        warning: { main: dracula.orange },
        info: { main: dracula.cyan },
        success: { main: dracula.green },

        text: {
            primary: dracula.foreground,
            secondary: alpha(dracula.foreground, 0.7),
            disabled: alpha(dracula.foreground, 0.45),
        },

        background: {
            default: dracula.background,
            paper: dracula.surface,
        },

        // Optional semantic slots you might use in components
        action: {
            active: alpha(dracula.foreground, 0.8),
            hover: alpha(dracula.foreground, 0.08),
            selected: alpha(dracula.purple, 0.18),
            disabled: alpha(dracula.foreground, 0.3),
            disabledBackground: alpha(dracula.foreground, 0.08),
            focus: alpha(dracula.cyan, 0.25),
            hoverOpacity: 0.08,
            disabledOpacity: 0.38,
            focusOpacity: 0.25,
            selectedOpacity: 0.18,
        },
    },

    shape: { borderRadius: 12 },

    typography: {
        fontFamily: [
            'Inter',
            'SF Pro Text',
            'Roboto',
            'Segoe UI',
            'Helvetica Neue',
            'Arial',
            'Noto Sans',
            'Apple Color Emoji',
            'Segoe UI Emoji',
            'Segoe UI Symbol',
        ].join(','),
        h1: { fontWeight: 700, letterSpacing: -0.5 },
        h2: { fontWeight: 700, letterSpacing: -0.3 },
        h3: { fontWeight: 700 },
        button: { textTransform: 'none', fontWeight: 600 },
    },

    components: {
        MuiPaper: {
            styleOverrides: {
                root: {
                    backgroundImage: 'none',
                    backgroundColor: dracula.surface,
                    border: `1px solid ${alpha(dracula.line, 0.6)}`,
                },
            },
        },
        MuiAppBar: {
            styleOverrides: {
                colorPrimary: {
                    backgroundColor: dracula.surfaceAlt,
                    borderBottom: `1px solid ${alpha(dracula.line, 0.7)}`,
                },
            },
        },
        MuiCard: {
            styleOverrides: {
                root: {
                    backgroundColor: dracula.surfaceAlt,
                    border: `1px solid ${alpha(dracula.line, 0.6)}`,
                },
            },
        },
        MuiButton: {
            styleOverrides: {
                root: { borderRadius: 10 },
                containedPrimary: {
                    color: dracula.background,
                },
                outlined: {
                    borderColor: alpha(dracula.foreground, 0.25),
                    ':hover': { borderColor: alpha(dracula.foreground, 0.45) },
                },
            },
        },
        MuiTextField: {
            defaultProps: { variant: 'outlined' },
        },
        MuiTooltip: {
            styleOverrides: {
                tooltip: {
                    backgroundColor: dracula.surfaceAlt,
                    color: dracula.foreground,
                    border: `1px solid ${alpha(dracula.line, 0.7)}`,
                },
            },
        },
        MuiDivider: {
            styleOverrides: {
                root: { borderColor: alpha(dracula.line, 0.6) },
            },
        },
        MuiChip: {
            styleOverrides: {
                root: {
                    backgroundColor: dracula.surface,
                    borderColor: alpha(dracula.line, 0.6),
                },
            },
        },
    },
});

// Optional light variant that keeps the Dracula hue identity but flips luminance
export const draculaLightTheme = createTheme({
    palette: {
        mode: 'light',
        primary: { main: dracula.purple },
        secondary: { main: dracula.cyan },
        error: { main: '#d64545' },
        warning: { main: '#ff9f43' },
        info: { main: dracula.cyan },
        success: { main: '#2ecc71' },

        background: {
            default: '#f7f8fb',
            paper: '#ffffff',
        },
        divider: alpha('#2d2f3a', 0.1),

        text: {
            primary: '#1b1c22',
            secondary: alpha('#1b1c22', 0.7),
            disabled: alpha('#1b1c22', 0.4),
        },
    },
    shape: { borderRadius: 12 },
    typography: { button: { textTransform: 'none', fontWeight: 600 } },
    components: {
        MuiPaper: { styleOverrides: { root: { backgroundImage: 'none' } } },
        MuiAppBar: {
            styleOverrides: { colorPrimary: { backgroundColor: '#ffffff' } },
        },
    },
});



import React, { useEffect, useState } from 'react';
import { useCookies } from 'react-cookie';
import { useNavigate, useSearchParams } from 'react-router';
import { verifyTokenRequest } from 'apis/auth';
import {
    AppBar,
    Box,
    Button,
    Chip,
    Container,
    Drawer,
    IconButton,
    Popover,
    Stack,
    Toolbar,
    Tooltip,
    Typography,
    useMediaQuery,
    useTheme,
} from '@mui/material';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import { login, logout } from 'reducers/auth';
import axios from 'axios';
import { useSWRConfig } from 'swr';
import DeletedImages from 'components/browse/DeletedImages';
import {
    AdminPanelSettingsRounded,
    CheckCircleOutlineRounded,
    ManageAccountsRounded,
    HomeRounded,
    LoginRounded,
    LogoutRounded,
    MenuRounded,
    MonitorHeartRounded,
    SearchRounded,
    UploadRounded,
} from '@mui/icons-material';
import DeviceSelect from 'pages/DeviceSelect';
import DRESSettings from 'components/meta/DRESSettings';
import NotificationsPanel from 'components/notifications/NotificationsPanel';
import ChatPanel from 'components/chat/ChatPanel';

const DRESWidget = () => {
    const [anchor, setAnchor] = useState<HTMLElement | null>(null);
    const { sessionId, evaluationId } = useAppSelector((s) => s.dres);
    const isLoggedIn = !!sessionId;
    return (
        <>
            {isLoggedIn ? (
                <Chip
                    icon={<CheckCircleOutlineRounded />}
                    label={evaluationId ? 'DRES' : 'DRES (no eval)'}
                    color="success"
                    size="small"
                    onClick={(e) => setAnchor(e.currentTarget)}
                    sx={{ cursor: 'pointer', ml: 1 }}
                />
            ) : (
                <Button
                    size="small"
                    startIcon={<LoginRounded />}
                    onClick={(e) => setAnchor(e.currentTarget)}
                    sx={{ ml: 1 }}
                >
                    DRES
                </Button>
            )}
            <Popover
                open={Boolean(anchor)}
                anchorEl={anchor}
                onClose={() => setAnchor(null)}
                anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
                transformOrigin={{ vertical: 'top', horizontal: 'right' }}
                slotProps={{ paper: { sx: { p: 2, minWidth: 320 } } }}
                keepMounted
            >
                <Typography variant="subtitle2" fontWeight="bold" mb={1}>
                    DRES Competition
                </Typography>
                <DRESSettings />
            </Popover>
        </>
    );
};

const PasswordLock = ({ children }: { children: React.ReactNode }) => {
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const { isAuthenticated, device } = useAppSelector((state) => state.auth);
    const dispatch = useAppDispatch();

    // The icon rail is a permanent Drawer on desktop; on a phone it has to slide
    // in instead, or it eats the viewport. No bottom bar here on purpose — the
    // Android host app draws its own tab bar along the bottom edge.
    const theme = useTheme();
    const isMobile = useMediaQuery(theme.breakpoints.down('md'));
    const [navOpen, setNavOpen] = useState(false);

    const navTo = React.useCallback((path: string, extra: Record<string, string | null> = {}) => {
        const params = new URLSearchParams();
        if (device) params.set('device', device);
        Object.entries(extra).forEach(([k, v]) => { if (v) params.set(k, v); });
        const qs = params.toString();
        setNavOpen(false);
        navigate(`${path}${qs ? '?' + qs : ''}`);
    }, [navigate, device]);
    const [cookies, _setCookies, removeCookies] = useCookies(['token']);

    const { mutate } = useSWRConfig();

    const clearAuthentication = () => {
        console.log('Clearing authentication');
        dispatch(logout());
        removeCookies('token', { path: '/' });
        axios.defaults.headers.common['Authorization'] = '';
        mutate(
            (_: any) => true,
            undefined, // update cache data to `undefined`
            { revalidate: false } // do not revalidate
        );
        navigate('/login');
    };

    useEffect(() => {
        if (cookies.token) {
            verifyTokenRequest(cookies.token)
                .then((response) => {
                    if (response.data.success) {
                        dispatch(
                            login({
                                username: response.data.username,
                                devices: response.data.devices,
                                sensors: response.data.sensors,
                            })
                        );
                        axios.defaults.headers.common['Authorization'] =
                            `Bearer ${cookies.token}`;
                    } else {
                        clearAuthentication();
                    }
                })
                .catch((error) => {
                    console.error('There was an error verifying token!', error);
                    clearAuthentication();
                });
        } else {
            clearAuthentication();
        }
    }, []);

    const navItems = [
        {
            title: 'Home',
            icon: <HomeRounded />,
            onClick: () => navTo('/', { date: searchParams.get('date') }),
        },
        {
            title: 'Insights',
            icon: <MonitorHeartRounded />,
            onClick: () => navTo('/insights', { date: searchParams.get('date') }),
        },
        {
            title: 'Search Images',
            icon: <SearchRounded />,
            onClick: () => navTo('/search'),
        },
        {
            title: 'Your Profile',
            icon: <ManageAccountsRounded />,
            onClick: () => navTo('/profile'),
        },
        {
            title: 'Admin Panel',
            icon: <AdminPanelSettingsRounded />,
            onClick: () => navTo('/admin'),
        },
        {
            title: 'Upload Images/Videos',
            icon: <UploadRounded />,
            onClick: () => navTo('/upload'),
        },
        {
            title: 'Logout',
            icon: <LogoutRounded />,
            onClick: clearAuthentication,
        },
    ];

    // Icon-only rail on desktop (tooltips carry the meaning); labelled rows on
    // mobile, where there is room for them and no hover to reveal a tooltip.
    const navContent = isMobile ? (
        <Stack spacing={0.5} mt={2} sx={{ width: 240 }}>
            {navItems.map((item) => (
                <Button
                    key={item.title}
                    color="secondary"
                    startIcon={item.icon}
                    onClick={item.onClick}
                    sx={{ justifyContent: 'flex-start', width: '100%', px: 2, py: 1 }}
                >
                    {item.title}
                </Button>
            ))}
            <DeletedImages label="Deleted Images" onOpen={() => setNavOpen(false)} />
        </Stack>
    ) : (
        <Stack spacing={2} alignItems="center" mt={2}>
            {navItems.map((item) => (
                <Tooltip key={item.title} title={item.title}>
                    <IconButton size="large" color="secondary" onClick={item.onClick}>
                        {item.icon}
                    </IconButton>
                </Tooltip>
            ))}
            <DeletedImages />
        </Stack>
    );

    if (isAuthenticated) {
        return (
            <>
                <AppBar
                    position="sticky"
                    color="transparent"
                    elevation={0}
                    sx={{
                        zIndex: (t) => t.zIndex.drawer + 1,
                        borderBottom: '1px solid',
                        borderColor: 'divider',
                        backdropFilter: 'blur(8px)',
                        ml: { xs: 0, md: 4 },
                        mr: { xs: 0, md: 4 },
                    }}
                >
                    <Toolbar sx={{ px: { xs: 1, md: 3 } }}>
                        {isMobile && (
                            <IconButton
                                edge="start"
                                color="secondary"
                                aria-label="Open navigation"
                                onClick={() => setNavOpen(true)}
                                sx={{ mr: 0.5 }}
                            >
                                <MenuRounded />
                            </IconButton>
                        )}
                        <Typography
                            variant="h6"
                            color="primary"
                            fontWeight="bold"
                            sx={{ mr: { xs: 0, md: 2 }, whiteSpace: 'nowrap' }}
                        >
                            SelfHealth
                        </Typography>
                        <Box sx={{ flex: 1 }} />
                        <DeviceSelect />
                        {!isMobile && <DRESWidget />}
                        <ChatPanel />
                        <NotificationsPanel />
                    </Toolbar>
                </AppBar>
                <Drawer
                    variant={isMobile ? 'temporary' : 'permanent'}
                    open={isMobile ? navOpen : true}
                    onClose={() => setNavOpen(false)}
                    ModalProps={{ keepMounted: true }}
                    sx={{ zIndex: 2200 }}
                >
                    {navContent}
                </Drawer>
                {/* Main Content */}
                <Container
                    maxWidth={false}
                    sx={{
                        ml: { xs: 0, md: 3 },
                        mt: 1,
                        px: { xs: 1, md: 3 },
                        maxHeight: 'calc(100vh - 88px)',
                        overflow: 'auto',
                    }}
                >
                    {children}
                </Container>
            </>
        );
    }
    return <></>;
};

export default PasswordLock;

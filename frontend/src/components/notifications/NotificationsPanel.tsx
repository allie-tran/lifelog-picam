import {
    Close,
    Notifications,
    NotificationsActive,
    NotificationsNone,
    PhonelinkRing,
} from '@mui/icons-material';
import {
    Badge,
    Box,
    Button,
    CircularProgress,
    Divider,
    Drawer,
    IconButton,
    List,
    ListItem,
    Stack,
    Toolbar,
    Tooltip,
    Typography,
} from '@mui/material';
import { THUMBNAIL_HOST_URL } from 'constants/urls';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { useCallback, useEffect, useState } from 'react';
import { sendTestPush } from '@apis/notifications';
import {
    clearAllNotifications,
    deleteNotification,
    fetchNotifications,
    markAllNotificationsRead,
    markNotificationsRead,
} from 'reducers/notifications';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import {
    disablePush,
    enablePush,
    getPushPermission,
    isPushSubscribed,
    pushSupported,
} from 'utils/push';

dayjs.extend(relativeTime);

const TYPE_LABELS: Record<string, string> = {
    new_location: '📍',
    unusual_activity: '✨',
    day_complete: '📋',
    novelty: '🌟',
    late_meal: '🍽️',
};

export default function NotificationsPanel() {
    const dispatch = useAppDispatch();
    const { items, unreadCount, loading } = useAppSelector((s) => s.notifications);
    const { isAuthenticated, device } = useAppSelector((s) => s.auth);

    const [open, setOpen] = useState(false);
    const [pushOn, setPushOn] = useState(false);
    const [pushBusy, setPushBusy] = useState(false);

    useEffect(() => {
        isPushSubscribed().then(setPushOn).catch(() => setPushOn(false));
    }, [open]);

    const togglePush = async () => {
        if (!device) return;
        setPushBusy(true);
        try {
            if (pushOn) {
                await disablePush();
                setPushOn(false);
            } else {
                const ok = await enablePush(device);
                setPushOn(ok);
                if (!ok && getPushPermission() === 'denied') {
                    alert('Notifications are blocked. Enable them in your browser/site settings.');
                }
            }
        } catch (e) {
            alert((e as Error).message || 'Could not change phone alerts');
        } finally {
            setPushBusy(false);
        }
    };

    const handleTestPush = async () => {
        if (!device) return;
        setPushBusy(true);
        try {
            const { data } = await sendTestPush(device);
            if (!data.ok) {
                alert(data.reason || 'No push sent — no active subscription on this device.');
            }
        } catch (e) {
            alert((e as Error).message || 'Test push failed');
        } finally {
            setPushBusy(false);
        }
    };

    const load = useCallback(() => {
        if (device && isAuthenticated) dispatch(fetchNotifications({ device }));
    }, [dispatch, device, isAuthenticated]);

    useEffect(() => {
        load();
        const interval = setInterval(load, 5 * 60 * 1000);
        return () => clearInterval(interval);
    }, [load]);

    const toogleOpen = () => {
        // setOpen(true);
        // load();
        if (!open) load();
        setOpen((o) => !o);
    };

    const handleMarkRead = (id: string) => {
        dispatch(markNotificationsRead({ device, ids: [id] }));
    };

    const handleMarkAll = () => {
        dispatch(markAllNotificationsRead(device));
    };

    const handleClearAll = () => {
        dispatch(clearAllNotifications(device));
    };

    const handleDelete = (id: string) => {
        dispatch(deleteNotification({ device, ids: [id] }));
    };

    if (!isAuthenticated) return null;

    return (
        <>
            <Tooltip title="Notifications">
                <IconButton
                    onClick={toogleOpen}
                    sx={{
                        ml: 1,
                        boxShadow: 2,
                        backgroundColor: 'background.paper',
                        '&:hover': { backgroundColor: 'background.paper' },
                    }}
                    size="small"
                >
                    <Badge badgeContent={unreadCount} color="primary" max={99}>
                        {unreadCount > 0 ? (
                            <Notifications color="primary" />
                        ) : (
                            <NotificationsNone color="action" />
                        )}
                    </Badge>
                </IconButton>
            </Tooltip>

            <Drawer anchor="right" open={open} onClose={() => setOpen(false)}>
                <Box sx={{ width: 360, display: 'flex', flexDirection: 'column', height: '100%' }}>
                    {/* Spacer so the header clears the sticky AppBar (zIndex drawer+1). */}
                    <Toolbar disableGutters sx={{ minHeight: { xs: 56, sm: 64 } }} />
                    <Stack
                        direction="row"
                        alignItems="center"
                        justifyContent="space-between"
                        sx={{ px: 2, py: 1.5 }}
                    >
                        <Typography variant="h6" fontWeight={700}>
                            Notifications{unreadCount > 0 ? ` (${unreadCount} new)` : ''}
                        </Typography>
                        <Stack direction="row" spacing={0.5}>
                            {unreadCount > 0 && (
                                <Button size="small" onClick={handleMarkAll}>
                                    Mark all read
                                </Button>
                            )}
                            {items.length > 0 && (
                                <Button size="small" color="error" onClick={handleClearAll}>
                                    Clear all
                                </Button>
                            )}
                        </Stack>
                    </Stack>
                    <Divider />

                    {loading && items.length === 0 ? (
                        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
                            <CircularProgress size={32} />
                        </Box>
                    ) : items.length === 0 ? (
                        <Box sx={{ textAlign: 'center', mt: 8 }}>
                            <Typography fontSize={40}>🔕</Typography>
                            <Typography color="text.secondary" mt={1}>
                                No notifications yet
                            </Typography>
                        </Box>
                    ) : (
                        <List sx={{ flex: 1, overflowY: 'auto', p: 1 }}>
                            {items.map((n) => (
                                <ListItem
                                    key={n.id}
                                    alignItems="flex-start"
                                    onClick={() => !n.read && handleMarkRead(n.id)}
                                    sx={{
                                        cursor: n.read ? 'default' : 'pointer',
                                        opacity: n.read ? 0.6 : 1,
                                        borderRadius: 2,
                                        mb: 0.5,
                                        borderLeft: 3,
                                        borderColor: n.read ? 'divider' : 'primary.main',
                                        backgroundColor: n.read ? 'transparent' : 'action.hover',
                                        '&:hover': { backgroundColor: 'action.hover' },
                                    }}
                                >
                                    <Stack direction="row" spacing={1.5} width="100%">
                                        <Typography fontSize={20} mt={0.25}>
                                            {TYPE_LABELS[n.type] ?? '🔔'}
                                        </Typography>
                                        <Box flex={1} minWidth={0}>
                                            <Stack direction="row" alignItems="center" justifyContent="space-between">
                                                <Box flex={1} minWidth={0} sx={{ m: 0 }}>
                                                    <Typography
                                                        fontSize={14}
                                                        fontWeight={n.read ? 400 : 700}
                                                        noWrap
                                                    >
                                                        {n.title}
                                                    </Typography>
                                                    {n.body && (
                                                        <Typography
                                                            fontSize={13}
                                                            color="text.secondary"
                                                            sx={{
                                                                overflow: 'hidden',
                                                                display: '-webkit-box',
                                                                WebkitLineClamp: 2,
                                                                WebkitBoxOrient: 'vertical',
                                                            }}
                                                        >
                                                            {n.body}
                                                        </Typography>
                                                    )}
                                                </Box>
                                                <Stack direction="row" alignItems="center" sx={{ ml: 1 }}>
                                                    {!n.read && (
                                                        <Box
                                                            sx={{
                                                                width: 8,
                                                                height: 8,
                                                                borderRadius: '50%',
                                                                backgroundColor: 'primary.main',
                                                                flexShrink: 0,
                                                            }}
                                                        />
                                                    )}
                                                    <Tooltip title="Dismiss">
                                                        <IconButton
                                                            size="small"
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                handleDelete(n.id);
                                                            }}
                                                            sx={{ ml: 0.5 }}
                                                        >
                                                            <Close fontSize="inherit" />
                                                        </IconButton>
                                                    </Tooltip>
                                                </Stack>
                                            </Stack>
                                            {n.imagePath && (
                                                <Box
                                                    component="img"
                                                    src={`${THUMBNAIL_HOST_URL}${n.imagePath}`}
                                                    alt=""
                                                    sx={{
                                                        width: '100%',
                                                        maxHeight: 120,
                                                        objectFit: 'cover',
                                                        borderRadius: 1,
                                                        mt: 0.5,
                                                    }}
                                                />
                                            )}
                                            <Typography fontSize={11} color="text.secondary" mt={0.5}>
                                                {n.timestamp
                                                    ? dayjs(n.timestamp).fromNow()
                                                    : n.date}
                                            </Typography>
                                        </Box>
                                    </Stack>
                                </ListItem>
                            ))}
                        </List>
                    )}

                    {pushSupported() && (
                        <>
                            <Divider />
                            <Box sx={{ p: 1.5 }}>
                                <Button
                                    fullWidth
                                    size="small"
                                    variant={pushOn ? 'outlined' : 'contained'}
                                    color={pushOn ? 'inherit' : 'primary'}
                                    disabled={pushBusy || !device}
                                    startIcon={
                                        pushBusy ? (
                                            <CircularProgress size={16} />
                                        ) : pushOn ? (
                                            <NotificationsActive />
                                        ) : (
                                            <PhonelinkRing />
                                        )
                                    }
                                    onClick={togglePush}
                                >
                                    {pushOn ? 'Phone alerts on' : 'Enable phone alerts'}
                                </Button>
                                {pushOn && (
                                    <Button
                                        fullWidth
                                        size="small"
                                        color="inherit"
                                        disabled={pushBusy || !device}
                                        onClick={handleTestPush}
                                        sx={{ mt: 0.5 }}
                                    >
                                        Send test notification
                                    </Button>
                                )}
                            </Box>
                        </>
                    )}
                </Box>
            </Drawer>
        </>
    );
}

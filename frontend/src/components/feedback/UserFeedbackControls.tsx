import ThumbUpAltIcon from '@mui/icons-material/ThumbUpAlt';
import ThumbUpOffAltIcon from '@mui/icons-material/ThumbUpOffAlt';
import ThumbDownAltIcon from '@mui/icons-material/ThumbDownAlt';
import ThumbDownOffAltIcon from '@mui/icons-material/ThumbDownOffAlt';
import OutlinedFlagIcon from '@mui/icons-material/OutlinedFlag';
import FeedbackOutlinedIcon from '@mui/icons-material/FeedbackOutlined';
import {
    Button,
    IconButton,
    MenuItem,
    Stack,
    TextField,
    Tooltip,
    Typography,
} from '@mui/material';
import React from 'react';
import ModalWithCloseButton from 'components/common/ModalWithCloseButton';
import { showNotification } from 'reducers/feedback';
import { useAppDispatch } from 'reducers/hooks';
import { getMyFeedback, submitFeedback } from 'apis/userFeedback';

// ---------------------------------------------------------------------------
// Shared "my ratings" cache — one fetch per targetType, shared by every thumb
// so a page of N segments doesn't fire N identical requests.
// ---------------------------------------------------------------------------

type RatingCache = { map: Map<string, string | null>; loaded: boolean; promise?: Promise<void> };
const ratingCache: Record<string, RatingCache> = {};

function useMyRating(targetType: string, targetId: string) {
    const [value, setValue] = React.useState<string | null>(null);

    React.useEffect(() => {
        let active = true;
        const cache = (ratingCache[targetType] ||= { map: new Map(), loaded: false });
        const apply = () => {
            if (active) setValue(cache.map.get(targetId) ?? null);
        };
        if (cache.loaded) {
            apply();
        } else {
            const pending =
                cache.promise ||
                (cache.promise = getMyFeedback(targetType)
                    .then((rows) => {
                        rows.forEach((r) => {
                            if (r.targetId) cache.map.set(r.targetId, r.value);
                        });
                        cache.loaded = true;
                    })
                    .catch(() => {
                        cache.loaded = true;
                    }));
            void pending.then(apply);
        }
        return () => {
            active = false;
        };
    }, [targetType, targetId]);

    const write = (v: string | null) => {
        const cache = (ratingCache[targetType] ||= { map: new Map(), loaded: false });
        cache.map.set(targetId, v);
        setValue(v);
    };

    return [value, write] as const;
}

// ---------------------------------------------------------------------------
// Rating thumbs (up / down). Clicking the active thumb again un-rates.
// ---------------------------------------------------------------------------

export const RatingThumbs = ({
    device,
    targetType,
    targetId,
    meta,
    size = 'small',
}: {
    device?: string;
    targetType: string;
    targetId: string;
    meta?: Record<string, unknown>;
    size?: 'small' | 'medium';
}) => {
    const [value, write] = useMyRating(targetType, targetId);

    const rate = (next: 'up' | 'down') => {
        const newValue = value === next ? null : next; // toggle off if same
        write(newValue);
        submitFeedback({ kind: 'rating', targetType, targetId, value: newValue, meta, device }).catch(
            () => write(value) // revert on failure
        );
    };

    return (
        <Stack direction="row" spacing={0.5} alignItems="center">
            <Tooltip title="Good result">
                <IconButton size={size} color={value === 'up' ? 'primary' : 'default'} onClick={() => rate('up')}>
                    {value === 'up' ? <ThumbUpAltIcon fontSize="inherit" /> : <ThumbUpOffAltIcon fontSize="inherit" />}
                </IconButton>
            </Tooltip>
            <Tooltip title="Bad result">
                <IconButton size={size} color={value === 'down' ? 'error' : 'default'} onClick={() => rate('down')}>
                    {value === 'down' ? (
                        <ThumbDownAltIcon fontSize="inherit" />
                    ) : (
                        <ThumbDownOffAltIcon fontSize="inherit" />
                    )}
                </IconButton>
            </Tooltip>
        </Stack>
    );
};

// ---------------------------------------------------------------------------
// Flag a specific item — opens a reason dialog.
// ---------------------------------------------------------------------------

const FLAG_REASONS: { value: string; label: string }[] = [
    { value: 'wrong', label: 'Wrong / inaccurate' },
    { value: 'private', label: 'Private — should be hidden' },
    { value: 'delete-request', label: 'Please delete this' },
    { value: 'other', label: 'Other' },
];

export const FlagButton = ({
    device,
    targetType,
    targetId,
    asMenuItem = false,
    onDone,
}: {
    device?: string;
    targetType: string;
    targetId: string;
    asMenuItem?: boolean;
    onDone?: () => void;
}) => {
    const dispatch = useAppDispatch();
    const [open, setOpen] = React.useState(false);
    const [reason, setReason] = React.useState('wrong');
    const [comment, setComment] = React.useState('');
    const [saving, setSaving] = React.useState(false);

    const submit = () => {
        setSaving(true);
        submitFeedback({ kind: 'flag', targetType, targetId, value: reason, comment, device })
            .then(() => {
                dispatch(showNotification({ message: 'Flagged for review. Thanks!', type: 'success' }));
                setOpen(false);
                setComment('');
                onDone?.();
            })
            .catch(() => dispatch(showNotification({ message: 'Could not submit flag.', type: 'error' })))
            .finally(() => setSaving(false));
    };

    return (
        <>
            {asMenuItem ? (
                <MenuItem
                    onClick={() => {
                        setOpen(true);
                        onDone?.();
                    }}
                >
                    <OutlinedFlagIcon fontSize="small" sx={{ mr: 1 }} />
                    Flag / report
                </MenuItem>
            ) : (
                <Tooltip title="Flag / report">
                    <Button
                        color="warning"
                        startIcon={<OutlinedFlagIcon />}
                        onClick={() => setOpen(true)}
                        sx={{ textTransform: 'none', p: 0 }}
                    >
                        Flag
                    </Button>
                </Tooltip>
            )}
            <ModalWithCloseButton open={open} onClose={() => setOpen(false)} fitContent>
                <Stack spacing={2} sx={{ p: 1, width: { xs: '80vw', sm: 380 }, maxWidth: '100%' }}>
                    <Typography variant="h6">Flag this item</Typography>
                    <TextField select label="Reason" value={reason} onChange={(e) => setReason(e.target.value)}>
                        {FLAG_REASONS.map((r) => (
                            <MenuItem key={r.value} value={r.value}>
                                {r.label}
                            </MenuItem>
                        ))}
                    </TextField>
                    <TextField
                        label="Details (optional)"
                        multiline
                        minRows={3}
                        value={comment}
                        onChange={(e) => setComment(e.target.value)}
                    />
                    <Button variant="contained" onClick={submit} disabled={saving}>
                        Submit flag
                    </Button>
                </Stack>
            </ModalWithCloseButton>
        </>
    );
};

// ---------------------------------------------------------------------------
// Global "send feedback / report a bug" button.
// ---------------------------------------------------------------------------

export const ReportButton = ({
    device,
    variant = 'button',
}: {
    device?: string;
    variant?: 'button' | 'icon';
}) => {
    const dispatch = useAppDispatch();
    const [open, setOpen] = React.useState(false);
    const [comment, setComment] = React.useState('');
    const [saving, setSaving] = React.useState(false);

    const submit = () => {
        if (!comment.trim()) return;
        setSaving(true);
        submitFeedback({ kind: 'report', comment, device })
            .then(() => {
                dispatch(showNotification({ message: 'Thanks for the feedback!', type: 'success' }));
                setOpen(false);
                setComment('');
            })
            .catch(() => dispatch(showNotification({ message: 'Could not send feedback.', type: 'error' })))
            .finally(() => setSaving(false));
    };

    return (
        <>
            {variant === 'icon' ? (
                <Tooltip title="Send feedback">
                    <IconButton onClick={() => setOpen(true)}>
                        <FeedbackOutlinedIcon />
                    </IconButton>
                </Tooltip>
            ) : (
                <Button startIcon={<FeedbackOutlinedIcon />} onClick={() => setOpen(true)} sx={{ textTransform: 'none' }}>
                    Send feedback
                </Button>
            )}
            <ModalWithCloseButton open={open} onClose={() => setOpen(false)} fitContent>
                <Stack spacing={2} sx={{ p: 1, width: { xs: '80vw', sm: 420 }, maxWidth: '100%' }}>
                    <Typography variant="h6">Send feedback</Typography>
                    <Typography variant="body2" color="text.secondary">
                        Report a bug or suggest an improvement. This goes to the admins.
                    </Typography>
                    <TextField
                        label="Your message"
                        multiline
                        minRows={4}
                        value={comment}
                        onChange={(e) => setComment(e.target.value)}
                    />
                    <Button variant="contained" onClick={submit} disabled={saving || !comment.trim()}>
                        Send
                    </Button>
                </Stack>
            </ModalWithCloseButton>
        </>
    );
};

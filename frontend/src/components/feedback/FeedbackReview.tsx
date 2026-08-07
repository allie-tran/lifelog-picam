import {
    Button,
    Chip,
    MenuItem,
    Stack,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableRow,
    TextField,
    Typography,
} from '@mui/material';
import React from 'react';
import useSWR from 'swr';
import {
    FeedbackRecord,
    FeedbackStatus,
    listFeedback,
    updateFeedbackStatus,
} from 'apis/userFeedback';

const STATUS_OPTIONS: FeedbackStatus[] = ['open', 'reviewed', 'resolved'];
const NEXT_STATUS: Record<FeedbackStatus, FeedbackStatus | null> = {
    open: 'reviewed',
    reviewed: 'resolved',
    resolved: null,
};

const statusColor = (s: FeedbackStatus): 'warning' | 'info' | 'success' =>
    s === 'open' ? 'warning' : s === 'reviewed' ? 'info' : 'success';

const FeedbackReview = () => {
    const [status, setStatus] = React.useState<FeedbackStatus>('open');

    // Flags + reports for the review queue (ratings are shown as an aggregate only).
    const { data: queue, mutate } = useSWR(['feedback-queue', status], () =>
        listFeedback({ status, limit: 300 }).then((rows) =>
            rows.filter((r) => r.kind !== 'rating')
        )
    );

    // Ratings aggregate (up/down counts).
    const { data: ratings } = useSWR(['feedback-ratings'], () =>
        listFeedback({ kind: 'rating', limit: 1000 })
    );

    const ups = ratings?.filter((r) => r.value === 'up').length ?? 0;
    const downs = ratings?.filter((r) => r.value === 'down').length ?? 0;

    const advance = async (row: FeedbackRecord) => {
        const next = NEXT_STATUS[row.status];
        if (!next) return;
        await updateFeedbackStatus(row.id, next);
        mutate();
    };

    return (
        <Stack spacing={2} width="100%">
            <Typography variant="h5">Feedback &amp; Reports</Typography>

            <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
                <Chip label={`👍 ${ups}`} color="primary" variant="outlined" />
                <Chip label={`👎 ${downs}`} color="error" variant="outlined" />
                <TextField
                    select
                    size="small"
                    label="Status"
                    value={status}
                    onChange={(e) => setStatus(e.target.value as FeedbackStatus)}
                    sx={{ minWidth: 140 }}
                >
                    {STATUS_OPTIONS.map((s) => (
                        <MenuItem key={s} value={s}>
                            {s}
                        </MenuItem>
                    ))}
                </TextField>
            </Stack>

            <Stack sx={{ width: '100%', overflowX: 'auto' }}>
                <Table size="small">
                    <TableHead>
                        <TableRow>
                            <TableCell>Kind</TableCell>
                            <TableCell>User</TableCell>
                            <TableCell>Target</TableCell>
                            <TableCell>Reason</TableCell>
                            <TableCell>Comment</TableCell>
                            <TableCell>When</TableCell>
                            <TableCell>Status</TableCell>
                            <TableCell align="right">Action</TableCell>
                        </TableRow>
                    </TableHead>
                    <TableBody>
                        {queue?.map((row) => (
                            <TableRow key={row.id}>
                                <TableCell>
                                    <Chip
                                        size="small"
                                        label={row.kind}
                                        color={row.kind === 'flag' ? 'warning' : 'default'}
                                    />
                                </TableCell>
                                <TableCell>{row.username}</TableCell>
                                <TableCell>
                                    {row.targetType ? `${row.targetType}:${row.targetId ?? ''}` : '—'}
                                </TableCell>
                                <TableCell>{row.value ?? '—'}</TableCell>
                                <TableCell sx={{ maxWidth: 260, whiteSpace: 'pre-wrap' }}>
                                    {row.comment ?? '—'}
                                </TableCell>
                                <TableCell>
                                    {row.createdAt ? new Date(row.createdAt).toLocaleString() : '—'}
                                </TableCell>
                                <TableCell>
                                    <Chip size="small" label={row.status} color={statusColor(row.status)} />
                                </TableCell>
                                <TableCell align="right">
                                    {NEXT_STATUS[row.status] && (
                                        <Button size="small" onClick={() => advance(row)}>
                                            Mark {NEXT_STATUS[row.status]}
                                        </Button>
                                    )}
                                </TableCell>
                            </TableRow>
                        ))}
                        {queue && queue.length === 0 && (
                            <TableRow>
                                <TableCell colSpan={8}>
                                    <Typography variant="body2" color="text.secondary" align="center" sx={{ py: 2 }}>
                                        No {status} flags or reports.
                                    </Typography>
                                </TableCell>
                            </TableRow>
                        )}
                    </TableBody>
                </Table>
            </Stack>
        </Stack>
    );
};

export default FeedbackReview;

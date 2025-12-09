// src/pages/ProcessingStatusPage.tsx
import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
    Box,
    Container,
    LinearProgress,
    Typography,
    Button,
} from '@mui/material';
import { api } from 'constants/urls';
import { useAppSelector } from 'reducers/hooks';

interface ProcessingStatus {
    job_id: string;
    status: string; // "pending", "processing", "done", "error"
    progress: number; // 0–1
    message?: string | null;
}

const REFRESH_INTERVAL_MS = 5000;

export const ProcessingStatusPage: React.FC = () => {
    const navigate = useNavigate();
    const { jobId } = useParams<{ jobId: string }>();
    const { deviceId } = useAppSelector((state) => state.auth);
    const [status, setStatus] = useState<ProcessingStatus | null>(null);
    const [error, setError] = useState<string | null>(null);

    console.log('Job ID from params:', jobId);
    useEffect(() => {
        if (!jobId) return;

        let isCancelled = false;

        const fetchStatus = async () => {
            try {
                const res = await api.get(`/ingest/processing-status/${jobId}`);
                if (!isCancelled) {
                    setStatus(res.data);
                    setError(null);
                }
            } catch (err: any) {
                if (!isCancelled) {
                    setError(
                        err?.response?.data?.detail ?? 'Failed to fetch status'
                    );
                }
            }
        };

        fetchStatus();
        const intervalId = setInterval(fetchStatus, REFRESH_INTERVAL_MS);

        return () => {
            isCancelled = true;
            clearInterval(intervalId);
        };
    }, [jobId]);

    const progressPercent = status ? status.progress * 100 : 0;

    return (
        <Container maxWidth="sm" sx={{ py: 4 }}>
            <Typography variant="h5" gutterBottom>
                Processing status
            </Typography>

            {status && (
                <Box sx={{ mt: 2 }}>
                    <Typography variant="body1" gutterBottom>
                        Job ID: {status.job_id}
                    </Typography>
                    <Typography variant="body2" gutterBottom>
                        Status: {status.status}
                    </Typography>

                    <Box sx={{ mt: 2 }}>
                        <Typography variant="body2" gutterBottom>
                            Processing: {progressPercent.toFixed(0)}%
                        </Typography>
                        <LinearProgress
                            variant="determinate"
                            value={progressPercent}
                        />
                    </Box>

                    {status.message && (
                        <Typography variant="body2" sx={{ mt: 2 }}>
                            {status.message}
                        </Typography>
                    )}

                    {status.status === 'done' && (
                        <Box sx={{ mt: 3 }}>
                            <Button
                                variant="contained"
                                onClick={() =>
                                    navigate(`/?device=${deviceId || ''}`)
                                }
                            >
                                Continue
                            </Button>
                        </Box>
                    )}
                </Box>
            )}

            {error && (
                <Typography color="error" variant="body2" sx={{ mt: 2 }}>
                    {error}
                </Typography>
            )}
        </Container>
    );
};

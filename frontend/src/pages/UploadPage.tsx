import {
    Box,
    Button,
    Container,
    LinearProgress,
    Stack,
    TextField,
    Typography,
} from '@mui/material';
import { api } from 'constants/urls';
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAppSelector } from 'reducers/hooks';
import DeviceSelect from './DeviceSelect';

const CHUNK_SIZE = 5 * 1024 * 1024; // 5MB

export const UploadPage: React.FC = () => {
    const { deviceId: device } = useAppSelector((state) => state.auth);
    const [dateFormat, setDateFormat] = useState<string>('%Y%m%d_%H%M%S_000');
    const [file, setFile] = useState<File | null>(null);
    const [uploadProgress, setUploadProgress] = useState<number>(0);
    const [isUploading, setIsUploading] = useState<boolean>(false);
    const [error, setError] = useState<string | null>(null);

    const navigate = useNavigate();

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const f = e.target.files?.[0] ?? null;
        setFile(f);
    };

    const handleUpload = async () => {
        if (!file) return;

        setError(null);
        setIsUploading(true);
        setUploadProgress(0);

        try {
            // 1) init upload
            const initRes = await api.post('/ingest/init', {
                device,
                date_format: dateFormat,
            });
            const uploadId: string = initRes.data.uploadId;

            // 2) chunked upload
            const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
            let uploadedBytes = 0;

            for (let chunkIndex = 0; chunkIndex < totalChunks; chunkIndex++) {
                const start = chunkIndex * CHUNK_SIZE;
                const end = Math.min(start + CHUNK_SIZE, file.size);
                const blob = file.slice(start, end);

                const formData = new FormData();
                formData.append('upload_id', uploadId);
                formData.append('chunk_index', String(chunkIndex));
                formData.append('total_chunks', String(totalChunks));
                formData.append('chunk', blob, file.name);

                await api.post('/ingest/chunk', formData, {
                    onUploadProgress: (event) => {
                        if (!event.total) return;
                        // Progress within this chunk
                    },
                });

                uploadedBytes += blob.size;
                const overallProgress = (uploadedBytes / file.size) * 100;
                setUploadProgress(overallProgress);
            }

            // 3) mark complete & get jobId
            const completeRes = await api.post('/ingest/complete', {
                upload_id: uploadId,
            });
            const jobId: string = completeRes.data.jobId;

            setIsUploading(false);
            setUploadProgress(100);

            // navigate to processing status page
            navigate(`/status/${jobId}`);
        } catch (err: any) {
            console.error(err);
            setError(err?.response?.data?.detail ?? 'Upload failed');
            setIsUploading(false);
        }
    };

    return (
        <Container maxWidth="sm" sx={{ py: 4 }}>
            <Stack spacing={4}>
                <Typography variant="h5" gutterBottom>
                    Upload lifelog ZIP
                </Typography>

                <Box
                    sx={{
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 2,
                        mt: 2,
                    }}
                >
                    {/* Device selection */}
                    <DeviceSelect />

                    {/* Date parsing schema */}
                    <TextField
                        label="Date format (Python strptime)"
                        value={dateFormat}
                        onChange={(e) => setDateFormat(e.target.value)}
                        helperText='Example: "%Y%m%d_%H%M%S" for 20251124_093000.jpg'
                    />

                    {/* ZIP file chooser */}
                    <Button
                        size="large"
                        variant="outlined"
                        component="label"
                        sx={{ width: '200px', py: 1.5, my: 2 }}
                    >
                        {file ? file.name : 'Choose ZIP file'}
                        <input
                            type="file"
                            accept=".zip"
                            hidden
                            onChange={handleFileChange}
                        />
                    </Button>

                    {/* Upload button */}
                    <Button
                        size="large"
                        variant="contained"
                        disabled={!file || isUploading}
                        onClick={handleUpload}
                    >
                        {isUploading ? 'Uploading...' : 'Upload to Server'}
                    </Button>

                    {/* Progress bar */}
                    {isUploading && (
                        <Box sx={{ mt: 2 }}>
                            <Typography variant="body2" gutterBottom>
                                Uploading: {uploadProgress.toFixed(0)}%
                            </Typography>
                            <LinearProgress
                                variant="determinate"
                                value={uploadProgress}
                            />
                        </Box>
                    )}

                    {error && <Typography color="error">{error}</Typography>}
                </Box>
            </Stack>
        </Container>
    );
};

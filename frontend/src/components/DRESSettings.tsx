import {
    CheckCircleOutlineRounded,
    ClearAllRounded,
    LoginRounded,
    LogoutRounded,
    RefreshRounded,
    SendRounded,
} from '@mui/icons-material';
import {
    Box,
    Button,
    Chip,
    CircularProgress,
    FormControl,
    InputAdornment,
    InputLabel,
    MenuItem,
    Select,
    Stack,
    TextField,
    Tooltip,
    Typography,
} from '@mui/material';
import {
    Evaluation,
    Task,
    getActiveEvaluations,
    getCurrentTask,
    sendLoginRequest,
    submitText,
} from 'apis/dres';
import { useEffect, useState } from 'react';
import { dresLogin, dresLogout, setCurrentTask, setEvaluation, clearSubmittedImages } from 'reducers/dres';
import { showNotification } from 'reducers/feedback';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';

const POLL_INTERVAL_MS = 10_000;

const DRESSettings = () => {
    const dispatch = useAppDispatch();
    const cachedSessionId = localStorage.getItem('dresSessionId');
    const { sessionId, evaluationId, currentTask, submittedImages } = useAppSelector((s) => s.dres);

    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [loggingIn, setLoggingIn] = useState(false);
    const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
    const [loadingEvals, setLoadingEvals] = useState(false);

    const isLoggedIn = !!sessionId;

    useEffect(() => {
        // Automatically log in if sessionId exists (e.g. from previous session)
        if (cachedSessionId) {
            handleAutoLogin(cachedSessionId);
        }
    }, [cachedSessionId, dispatch]);

    // Poll current task when an evaluation is selected
    useEffect(() => {
        if (!evaluationId) return;

        const fetchTask = async () => {
            try {
                const res = await getCurrentTask(evaluationId);
                dispatch(setCurrentTask(res.data as Task));
            } catch {
                dispatch(setCurrentTask(null));
            }
        };

        fetchTask();
        const interval = setInterval(fetchTask, POLL_INTERVAL_MS);
        return () => clearInterval(interval);
    }, [evaluationId]);

    const autoSelectEvaluation = (evs: Evaluation[]) => {
        if (!evaluationId && evs.length > 0) {
            dispatch(setEvaluation(evs[0].id));
        }
    };

    const fetchEvaluations = async () => {
        setLoadingEvals(true);
        try {
            const res = await getActiveEvaluations();
            const evs = res.data as Evaluation[];
            setEvaluations(evs);
            autoSelectEvaluation(evs);
        } catch {
            dispatch(showNotification({ message: 'Failed to load evaluations', type: 'error' }));
        } finally {
            setLoadingEvals(false);
        }
    };

    const handleAutoLogin = async (sid: string) => {
        dispatch(dresLogin(sid));
        dispatch(showNotification({ message: 'Logged in to DRES', type: 'success' }));
        // immediately load evaluations
        setLoadingEvals(true);
        const evRes = await getActiveEvaluations();
        const evs = evRes.data as Evaluation[];
        setEvaluations(evs);
        autoSelectEvaluation(evs);
        setLoadingEvals(false);
    }

    const handleLogin = async () => {
        setLoggingIn(true);
        try {
            const res = await sendLoginRequest(username, password);
            const sid = res.data.sessionId ?? res.data.session ?? res.data.token;
            handleAutoLogin(sid);
        } catch (e: any) {
            dispatch(showNotification({
                message: e?.response?.data?.message ?? 'DRES login failed',
                type: 'error',
            }));
        } finally {
            setLoggingIn(false);
        }
    };

    const handleLogout = () => {
        dispatch(dresLogout());
        setEvaluations([]);
    };

    const [textAnswer, setTextAnswer] = useState('');
    const [submittingText, setSubmittingText] = useState(false);

    const handleTextSubmit = async () => {
        if (!evaluationId || !sessionId || !textAnswer.trim()) return;
        setSubmittingText(true);
        try {
            const result = await submitText({ text: textAnswer.trim(), evaluationId, sessionId });
            dispatch(showNotification({ message: `DRES: ${result.verdict} — ${result.message}`, type: result.severity }));
            setTextAnswer('');
        } catch {
            dispatch(showNotification({ message: 'DRES text submission failed', type: 'error' }));
        } finally {
            setSubmittingText(false);
        }
    };

    return (
        <Stack spacing={2} sx={{ p: 0, minWidth: 300, pr: 1 }}>
            {!isLoggedIn ? (
                <>
                    <TextField
                        label="DRES Username"
                        size="small"
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
                    />
                    <TextField
                        label="DRES Password"
                        type="password"
                        size="small"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
                    />
                    <Button
                        variant="contained"
                        startIcon={loggingIn ? <CircularProgress size={16} color="inherit" /> : <LoginRounded />}
                        onClick={handleLogin}
                        disabled={loggingIn || !username || !password}
                    >
                        Login
                    </Button>
                </>
            ) : (
                <>
                    <Stack direction="row" alignItems="center" justifyContent="space-between">
                        <Chip
                            icon={<CheckCircleOutlineRounded />}
                            label="Connected to DRES"
                            color="success"
                            size="small"
                        />
                        <Stack direction="row" spacing={0.5}>
                            <Tooltip title={`Clear submission history (${submittedImages.length} images)`}>
                                <span>
                                    <Button
                                        size="small"
                                        color="warning"
                                        startIcon={<ClearAllRounded />}
                                        onClick={() => dispatch(clearSubmittedImages())}
                                        disabled={submittedImages.length === 0}
                                    >
                                        Clear
                                    </Button>
                                </span>
                            </Tooltip>
                            <Button
                                size="small"
                                color="error"
                                startIcon={<LogoutRounded />}
                                onClick={handleLogout}
                            >
                                Logout
                            </Button>
                        </Stack>
                    </Stack>

                    <Stack direction="row" spacing={1} alignItems="center">
                        <FormControl size="small" fullWidth>
                            <InputLabel>Evaluation</InputLabel>
                            <Select
                                label="Evaluation"
                                value={evaluationId ?? ''}
                                onChange={(e) => dispatch(setEvaluation(e.target.value))}
                            >
                                {evaluations.map((ev) => (
                                    <MenuItem key={ev.id} value={ev.id}>
                                        {ev.name}
                                    </MenuItem>
                                ))}
                            </Select>
                        </FormControl>
                        <Tooltip title="Refresh evaluations">
                            <span>
                                <Button
                                    size="small"
                                    variant="outlined"
                                    onClick={fetchEvaluations}
                                    disabled={loadingEvals}
                                    sx={{ minWidth: 40, px: 1 }}
                                >
                                    {loadingEvals
                                        ? <CircularProgress size={16} />
                                        : <RefreshRounded fontSize="small" />}
                                </Button>
                            </span>
                        </Tooltip>
                    </Stack>

                    {currentTask ? (
                        <Box
                            sx={{
                                p: 1.5,
                                borderRadius: 1,
                                bgcolor: 'action.hover',
                                border: '1px solid',
                                borderColor: 'divider',
                            }}
                        >
                            <Typography variant="caption" color="text.secondary">
                                Current task
                            </Typography>
                            <Typography variant="body2" fontWeight="bold">
                                {currentTask.name}
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                                {currentTask.taskGroup} · {currentTask.taskType} · {currentTask.duration}s
                            </Typography>
                        </Box>
                    ) : evaluationId ? (
                        <Typography variant="caption" color="text.secondary">
                            No active task
                        </Typography>
                    ) : null}

                    {evaluationId && (
                        <TextField
                            label={currentTask?.taskType === 'QA' ? 'Text answer (QA)' : 'Text answer'}
                            size="small"
                            fullWidth
                            value={textAnswer}
                            onChange={(e) => setTextAnswer(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleTextSubmit()}
                            disabled={submittingText}
                            slotProps={{
                                input: {
                                    endAdornment: (
                                        <InputAdornment position="end">
                                            <Tooltip title="Submit text answer">
                                                <span>
                                                    <Button
                                                        size="small"
                                                        color="success"
                                                        onClick={handleTextSubmit}
                                                        disabled={submittingText || !textAnswer.trim()}
                                                        sx={{ minWidth: 32, px: 0.5 }}
                                                    >
                                                        {submittingText
                                                            ? <CircularProgress size={14} color="inherit" />
                                                            : <SendRounded fontSize="small" />}
                                                    </Button>
                                                </span>
                                            </Tooltip>
                                        </InputAdornment>
                                    ),
                                },
                            }}
                        />
                    )}
                </>
            )}
        </Stack>
    );
};

export default DRESSettings;

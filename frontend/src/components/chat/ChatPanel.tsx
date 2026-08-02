import { Add, Close, DeleteOutline, DeleteSweepOutlined, PsychologyOutlined, SmartToyOutlined, Send } from '@mui/icons-material';
import {
    Box,
    Button,
    Chip,
    CircularProgress,
    Divider,
    Drawer,
    IconButton,
    Stack,
    TextField,
    Toolbar,
    Tooltip,
    Typography,
} from '@mui/material';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router';
import { useSWRConfig } from 'swr';
import { AppliedAction, ChatMemory } from '@utils/types';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import {
    clearThread,
    closePanel,
    fetchMemories,
    loadThread,
    removeMemory,
    saveMemory,
    sendMessageStream,
    togglePanel,
} from 'reducers/chat';

// Tools whose effects change the rendered day/period — refresh those SWR caches.
const REFRESH_TOOLS = new Set([
    'edit_segment_activity',
    'edit_day_summary_text',
    'change_location',
]);

export default function ChatPanel() {
    const [searchParams] = useSearchParams();
    const date = searchParams.get('date') || undefined;
    const { isAuthenticated, device } = useAppSelector((s) => s.auth);
    const { open, messages, streaming, lastUsage, totalUsage, memories } = useAppSelector((s) => s.chat);
    const dispatch = useAppDispatch();
    const { mutate } = useSWRConfig();

    const [input, setInput] = useState('');
    const [showMemory, setShowMemory] = useState(false);
    const [newKey, setNewKey] = useState('');
    const [newText, setNewText] = useState('');
    const listRef = useRef<HTMLDivElement | null>(null);

    // Day threads are keyed device:date — resume the transcript when opened.
    const threadId = date && device ? `${device}:${date}` : undefined;

    useEffect(() => {
        if (open && device && threadId) {
            dispatch(loadThread({ device, threadId }));
        }
    }, [open, device, threadId, dispatch]);

    useEffect(() => {
        if (open && showMemory && device) dispatch(fetchMemories(device));
    }, [open, showMemory, device, dispatch]);

    const savedKeys = new Set(memories.map((m) => m.key));

    useEffect(() => {
        listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' });
    }, [messages, streaming]);

    const refreshAffectedViews = useCallback((actions: AppliedAction[]) => {
        if (actions.some((a) => REFRESH_TOOLS.has(a.tool))) {
            mutate((k: any) => !!k && (k.key === 'day-summary' || k.key === 'period-summary'));
        }
    }, [mutate]);

    // Slash commands typed in the input. Returns true if handled (not sent to the LLM).
    const runCommand = (text: string): boolean => {
        const [cmd] = text.slice(1).trim().toLowerCase().split(/\s+/);
        switch (cmd) {
            case 'clear':
                dispatch(clearThread({ threadId }));
                return true;
            case 'memory':
            case 'memories':
                setShowMemory(true);
                return true;
            case 'help':
                window.alert('Commands:\n/clear — clear this conversation\n/memory — view remembered facts');
                return true;
            default:
                return false; // unknown → fall through and send as a normal message
        }
    };

    const handleSend = async () => {
        const text = input.trim();
        if (!text || !device || streaming) return;
        if (text.startsWith('/') && runCommand(text)) {
            setInput('');
            return;
        }
        setInput('');
        const res = await dispatch(
            sendMessageStream({
                device,
                text,
                scope: date ? 'day' : 'global',
                date: date ?? null,
                threadId,
            }),
        ).unwrap();
        if (res?.appliedActions) refreshAffectedViews(res.appliedActions);
    };

    const handleSaveMemory = (key: string, text: string) => {
        if (device) dispatch(saveMemory({ device, key, text }));
    };

    const handleAddMemory = () => {
        const key = newKey.trim();
        if (!key || !device) return;
        dispatch(saveMemory({ device, key, text: newText.trim() }));
        setNewKey('');
        setNewText('');
    };

    const handleClear = () => {
        if (streaming) return;
        if (messages.length && !window.confirm('Clear this conversation?')) return;
        dispatch(clearThread({ threadId }));
    };

    if (!isAuthenticated) return null;

    return (
        <>
            <Tooltip title="Chat about this day">
                <IconButton
                    onClick={() => dispatch(togglePanel())}
                    sx={{
                        ml: 1,
                        boxShadow: 2,
                        backgroundColor: 'background.paper',
                        '&:hover': { backgroundColor: 'background.paper' },
                    }}
                    size="small"
                >
                    <SmartToyOutlined color={open ? 'primary' : 'action'} />
                </IconButton>
            </Tooltip>

            <Drawer anchor="right" open={open} onClose={() => dispatch(closePanel())}>
                <Box sx={{ width: { xs: '100vw', sm: 400 }, maxWidth: '100vw', display: 'flex', flexDirection: 'column', height: '100%' }}>
                    {/* Spacer so the header clears the sticky AppBar. */}
                    <Toolbar disableGutters sx={{ minHeight: { xs: 56, sm: 64 } }} />
                    <Stack
                        direction="row"
                        alignItems="center"
                        justifyContent="space-between"
                        sx={{ px: 2, py: 1.5 }}
                    >
                        <Box>
                            <Typography variant="h6" fontWeight={700}>
                                {showMemory ? 'Memory' : 'Day assistant'}
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                                {showMemory
                                    ? `${memories.length} remembered fact${memories.length === 1 ? '' : 's'}`
                                    : date ? `Chatting about ${date}` : 'General assistant'}
                            </Typography>
                        </Box>
                        <Stack direction="row" spacing={0.5}>
                            {!showMemory && (
                                <Tooltip title="Clear conversation">
                                    <span>
                                        <IconButton
                                            size="small"
                                            onClick={handleClear}
                                            disabled={streaming || messages.length === 0}
                                        >
                                            <DeleteSweepOutlined fontSize="small" />
                                        </IconButton>
                                    </span>
                                </Tooltip>
                            )}
                            <Tooltip title={showMemory ? 'Back to chat' : 'What I remember'}>
                                <IconButton size="small" onClick={() => setShowMemory((v) => !v)}>
                                    <PsychologyOutlined
                                        fontSize="small"
                                        color={showMemory ? 'primary' : 'action'}
                                    />
                                </IconButton>
                            </Tooltip>
                            <IconButton size="small" onClick={() => dispatch(closePanel())}>
                                <Close fontSize="inherit" />
                            </IconButton>
                        </Stack>
                    </Stack>
                    <Divider />

                    {showMemory ? (
                        <MemoryView
                            memories={memories}
                            newKey={newKey}
                            newText={newText}
                            setNewKey={setNewKey}
                            setNewText={setNewText}
                            onAdd={handleAddMemory}
                            onDelete={(key) => device && dispatch(removeMemory({ device, key }))}
                        />
                    ) : (
                    <>
                    <Box ref={listRef} sx={{ flex: 1, overflowY: 'auto', p: 2 }}>
                        {messages.length === 0 && !streaming ? (
                            <Box sx={{ textAlign: 'center', mt: 8 }}>
                                <Typography fontSize={40}>💬</Typography>
                                <Typography color="text.secondary" mt={1}>
                                    Ask about your day, or tell me to fix a label,
                                    rewrite the summary, or name a place.
                                </Typography>
                            </Box>
                        ) : (
                            <Stack spacing={1.5}>
                                {messages.map((m, i) => {
                                    const isLast = i === messages.length - 1;
                                    const showCursor = streaming && isLast && m.role === 'assistant';
                                    const suggestions = (m.appliedActions || []).filter(
                                        (a) => a.tool === 'suggest_memory',
                                    );
                                    const edits = (m.appliedActions || []).filter(
                                        (a) => a.tool !== 'suggest_memory',
                                    );
                                    return (
                                        <Box
                                            key={i}
                                            sx={{
                                                alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                                                maxWidth: '85%',
                                                px: 1.5,
                                                py: 1,
                                                borderRadius: 2,
                                                backgroundColor:
                                                    m.role === 'user' ? 'primary.main' : 'action.hover',
                                                color: m.role === 'user' ? 'primary.contrastText' : 'text.primary',
                                            }}
                                        >
                                            <Typography fontSize={14} sx={{ whiteSpace: 'pre-wrap' }}>
                                                {m.content}
                                                {showCursor && !m.content && (
                                                    <CircularProgress size={12} sx={{ ml: 0.5 }} />
                                                )}
                                                {showCursor && m.content ? ' ▍' : ''}
                                            </Typography>
                                            {edits.length > 0 && (
                                                <Stack direction="row" flexWrap="wrap" gap={0.5} mt={0.75}>
                                                    {edits.map((a, j) => (
                                                        <Chip
                                                            key={j}
                                                            size="small"
                                                            label={a.tool.replace(/_/g, ' ')}
                                                            color="success"
                                                            variant="outlined"
                                                        />
                                                    ))}
                                                </Stack>
                                            )}
                                            {suggestions.map((a, j) => {
                                                const key = String(a.args?.key ?? '');
                                                const text = String(a.args?.text ?? '');
                                                const saved = savedKeys.has(key);
                                                return (
                                                    <Stack
                                                        key={`s${j}`}
                                                        direction="row"
                                                        alignItems="center"
                                                        spacing={1}
                                                        mt={0.75}
                                                        sx={{
                                                            p: 0.75,
                                                            borderRadius: 1,
                                                            border: 1,
                                                            borderColor: 'divider',
                                                        }}
                                                    >
                                                        <PsychologyOutlined fontSize="small" color="action" />
                                                        <Typography fontSize={12} flex={1}>
                                                            Remember: {text}
                                                        </Typography>
                                                        <Button
                                                            size="small"
                                                            disabled={saved}
                                                            onClick={() => handleSaveMemory(key, text)}
                                                        >
                                                            {saved ? 'Saved' : 'Save'}
                                                        </Button>
                                                    </Stack>
                                                );
                                            })}
                                            {m.distilled && m.distilled.length > 0 && (
                                                <Typography fontSize={11} color="text.secondary" mt={0.5}>
                                                    🧠 Remembered: {m.distilled.map((d) => d.key).join(', ')}
                                                </Typography>
                                            )}
                                        </Box>
                                    );
                                })}
                            </Stack>
                        )}
                    </Box>

                    <Divider />
                    <Box sx={{ px: 2, py: 0.5 }}>
                        <Typography variant="caption" color="text.secondary">
                            Tokens — last: {lastUsage.total} · thread total: {totalUsage.total}
                        </Typography>
                    </Box>
                    <Box sx={{ p: 1.5, pt: 0.5 }}>
                        <Stack direction="row" spacing={1} alignItems="flex-end">
                            <TextField
                                fullWidth
                                size="small"
                                multiline
                                maxRows={4}
                                placeholder="Message the assistant…  (/clear, /memory)"
                                value={input}
                                onChange={(e) => setInput(e.target.value)}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter' && !e.shiftKey) {
                                        e.preventDefault();
                                        handleSend();
                                    }
                                }}
                                disabled={streaming}
                            />
                            <IconButton
                                color="primary"
                                onClick={handleSend}
                                disabled={streaming || !input.trim()}
                            >
                                <Send />
                            </IconButton>
                        </Stack>
                    </Box>
                    </>
                    )}
                </Box>
            </Drawer>
        </>
    );
}

interface MemoryViewProps {
    memories: ChatMemory[];
    newKey: string;
    newText: string;
    setNewKey: (v: string) => void;
    setNewText: (v: string) => void;
    onAdd: () => void;
    onDelete: (key: string) => void;
}

function MemoryView({
    memories, newKey, newText, setNewKey, setNewText, onAdd, onDelete,
}: MemoryViewProps) {
    return (
        <Box sx={{ flex: 1, overflowY: 'auto', p: 2, display: 'flex', flexDirection: 'column' }}>
            {memories.length === 0 ? (
                <Box sx={{ textAlign: 'center', mt: 6 }}>
                    <Typography fontSize={36}>🧠</Typography>
                    <Typography color="text.secondary" mt={1}>
                        Nothing remembered yet. Tell the assistant facts worth keeping,
                        or add one below.
                    </Typography>
                </Box>
            ) : (
                <Stack spacing={1} sx={{ flex: 1 }}>
                    {memories.map((m) => (
                        <Stack
                            key={m.key}
                            direction="row"
                            alignItems="flex-start"
                            spacing={1}
                            sx={{ p: 1, borderRadius: 1, border: 1, borderColor: 'divider' }}
                        >
                            <Box flex={1} minWidth={0}>
                                <Typography fontSize={12} fontWeight={700} color="primary">
                                    {m.key}
                                </Typography>
                                <Typography fontSize={13}>{m.text}</Typography>
                            </Box>
                            <IconButton size="small" onClick={() => onDelete(m.key)}>
                                <DeleteOutline fontSize="inherit" />
                            </IconButton>
                        </Stack>
                    ))}
                </Stack>
            )}
            <Divider sx={{ my: 1.5 }} />
            <Stack spacing={1}>
                <TextField
                    size="small"
                    label="Key"
                    placeholder="e.g. partner_name"
                    value={newKey}
                    onChange={(e) => setNewKey(e.target.value)}
                />
                <TextField
                    size="small"
                    label="Fact"
                    placeholder="e.g. Luca is the user's partner"
                    value={newText}
                    onChange={(e) => setNewText(e.target.value)}
                />
                <Button
                    startIcon={<Add />}
                    variant="outlined"
                    size="small"
                    disabled={!newKey.trim()}
                    onClick={onAdd}
                >
                    Add memory
                </Button>
            </Stack>
        </Box>
    );
}

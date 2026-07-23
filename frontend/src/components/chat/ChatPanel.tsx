import { Close, SmartToyOutlined, Send } from '@mui/icons-material';
import {
    Box,
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
import { getChatThread, sendChatMessage } from '@apis/chat';
import { AppliedAction, ChatMessage, TokenUsage } from '@utils/types';
import { useAppSelector } from 'reducers/hooks';

const EMPTY_USAGE: TokenUsage = { prompt: 0, completion: 0, total: 0 };

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
    const { mutate } = useSWRConfig();

    const [open, setOpen] = useState(false);
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [totalUsage, setTotalUsage] = useState<TokenUsage>(EMPTY_USAGE);
    const [lastUsage, setLastUsage] = useState<TokenUsage>(EMPTY_USAGE);
    const listRef = useRef<HTMLDivElement | null>(null);

    // Day threads are keyed device:date — load the transcript when the panel
    // opens against a day so the conversation resumes.
    const threadId = date && device ? `${device}:${date}` : undefined;

    const loadThread = useCallback(async () => {
        if (!device || !threadId) return;
        try {
            const t = await getChatThread(device, threadId);
            setMessages(t.messages || []);
            setTotalUsage(t.tokenUsage || EMPTY_USAGE);
        } catch {
            // No thread yet — fresh conversation.
            setMessages([]);
            setTotalUsage(EMPTY_USAGE);
        }
    }, [device, threadId]);

    useEffect(() => {
        if (open) loadThread();
    }, [open, loadThread]);

    useEffect(() => {
        listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' });
    }, [messages, loading]);

    const refreshAffectedViews = (actions: AppliedAction[]) => {
        if (actions.some((a) => REFRESH_TOOLS.has(a.tool))) {
            mutate((k: any) => !!k && (k.key === 'day-summary' || k.key === 'period-summary'));
        }
    };

    const handleSend = async () => {
        const text = input.trim();
        if (!text || !device || loading) return;
        setInput('');
        setMessages((m) => [...m, { role: 'user', content: text }]);
        setLoading(true);
        try {
            const res = await sendChatMessage(device, text, {
                scope: date ? 'day' : 'global',
                date: date ?? null,
                threadId,
            });
            setMessages((m) => [
                ...m,
                {
                    role: 'assistant',
                    content: res.reply,
                    appliedActions: res.appliedActions,
                    tokenUsage: res.messageUsage,
                },
            ]);
            setLastUsage(res.messageUsage);
            setTotalUsage(res.totalUsage);
            refreshAffectedViews(res.appliedActions || []);
        } catch (e) {
            setMessages((m) => [
                ...m,
                { role: 'assistant', content: `⚠️ ${(e as Error).message || 'Chat failed'}` },
            ]);
        } finally {
            setLoading(false);
        }
    };

    if (!isAuthenticated) return null;

    return (
        <>
            <Tooltip title="Chat about this day">
                <IconButton
                    onClick={() => setOpen((o) => !o)}
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

            <Drawer anchor="right" open={open} onClose={() => setOpen(false)}>
                <Box sx={{ width: 400, display: 'flex', flexDirection: 'column', height: '100%' }}>
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
                                Day assistant
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                                {date ? `Chatting about ${date}` : 'General assistant'}
                            </Typography>
                        </Box>
                        <IconButton size="small" onClick={() => setOpen(false)}>
                            <Close fontSize="inherit" />
                        </IconButton>
                    </Stack>
                    <Divider />

                    <Box ref={listRef} sx={{ flex: 1, overflowY: 'auto', p: 2 }}>
                        {messages.length === 0 && !loading ? (
                            <Box sx={{ textAlign: 'center', mt: 8 }}>
                                <Typography fontSize={40}>💬</Typography>
                                <Typography color="text.secondary" mt={1}>
                                    Ask about your day, or tell me to fix a label,
                                    rewrite the summary, or name a place.
                                </Typography>
                            </Box>
                        ) : (
                            <Stack spacing={1.5}>
                                {messages.map((m, i) => (
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
                                        </Typography>
                                        {m.appliedActions && m.appliedActions.length > 0 && (
                                            <Stack direction="row" flexWrap="wrap" gap={0.5} mt={0.75}>
                                                {m.appliedActions.map((a, j) => (
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
                                    </Box>
                                ))}
                                {loading && (
                                    <Box sx={{ alignSelf: 'flex-start', p: 1 }}>
                                        <CircularProgress size={18} />
                                    </Box>
                                )}
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
                                placeholder="Message the assistant…"
                                value={input}
                                onChange={(e) => setInput(e.target.value)}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter' && !e.shiftKey) {
                                        e.preventDefault();
                                        handleSend();
                                    }
                                }}
                                disabled={loading}
                            />
                            <IconButton
                                color="primary"
                                onClick={handleSend}
                                disabled={loading || !input.trim()}
                            >
                                <Send />
                            </IconButton>
                        </Stack>
                    </Box>
                </Box>
            </Drawer>
        </>
    );
}

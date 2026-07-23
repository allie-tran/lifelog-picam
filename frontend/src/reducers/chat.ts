import { createAsyncThunk, createSlice, PayloadAction } from '@reduxjs/toolkit';
import {
    getChatThread,
    streamChatMessage,
    StreamDonePayload,
} from '@apis/chat';
import { AppliedAction, ChatMessage, TokenUsage } from '@utils/types';

const EMPTY_USAGE: TokenUsage = { prompt: 0, completion: 0, total: 0 };

interface ChatState {
    open: boolean;
    threadId?: string;
    date?: string;
    messages: ChatMessage[];
    streaming: boolean;
    loadingThread: boolean;
    lastUsage: TokenUsage;
    totalUsage: TokenUsage;
    error: string | null;
}

const initialState: ChatState = {
    open: false,
    messages: [],
    streaming: false,
    loadingThread: false,
    lastUsage: EMPTY_USAGE,
    totalUsage: EMPTY_USAGE,
    error: null,
};

// Load an existing day/global thread transcript.
export const loadThread = createAsyncThunk(
    'chat/loadThread',
    async ({ device, threadId }: { device: string; threadId: string }) => {
        return await getChatThread(device, threadId);
    },
);

// Send a message and stream the reply, dispatching deltas/tools as they arrive.
// Returns the final done payload so the caller can refresh affected SWR views.
export const sendMessageStream = createAsyncThunk(
    'chat/sendStream',
    async (
        args: { device: string; text: string; scope: 'day' | 'global'; date?: string | null; threadId?: string },
        { dispatch },
    ): Promise<StreamDonePayload | null> => {
        dispatch(chatSlice.actions.addUserMessage(args.text));
        dispatch(chatSlice.actions.beginAssistant());
        let done: StreamDonePayload | null = null;
        await streamChatMessage(
            args.device,
            args.text,
            { scope: args.scope, date: args.date, threadId: args.threadId },
            {
                onDelta: (t) => dispatch(chatSlice.actions.appendDelta(t)),
                onTool: (a) => dispatch(chatSlice.actions.addToolAction(a)),
                onDone: (d) => {
                    done = d;
                    dispatch(chatSlice.actions.finishAssistant(d));
                },
                onError: (m) => dispatch(chatSlice.actions.streamError(m)),
            },
        );
        return done;
    },
);

const chatSlice = createSlice({
    name: 'chat',
    initialState,
    reducers: {
        openPanel: (state) => { state.open = true; },
        closePanel: (state) => { state.open = false; },
        togglePanel: (state) => { state.open = !state.open; },
        setDate: (state, action: PayloadAction<string | undefined>) => {
            state.date = action.payload;
        },
        addUserMessage: (state, action: PayloadAction<string>) => {
            state.messages.push({ role: 'user', content: action.payload });
            state.error = null;
        },
        beginAssistant: (state) => {
            state.streaming = true;
            state.messages.push({ role: 'assistant', content: '', appliedActions: [] });
        },
        appendDelta: (state, action: PayloadAction<string>) => {
            const last = state.messages[state.messages.length - 1];
            if (last && last.role === 'assistant') last.content += action.payload;
        },
        addToolAction: (state, action: PayloadAction<AppliedAction>) => {
            const last = state.messages[state.messages.length - 1];
            if (last && last.role === 'assistant') {
                (last.appliedActions ||= []).push(action.payload);
            }
        },
        finishAssistant: (state, action: PayloadAction<StreamDonePayload>) => {
            state.streaming = false;
            state.threadId = action.payload.threadId;
            state.lastUsage = action.payload.messageUsage;
            state.totalUsage = action.payload.totalUsage;
            const last = state.messages[state.messages.length - 1];
            if (last && last.role === 'assistant') last.tokenUsage = action.payload.messageUsage;
        },
        streamError: (state, action: PayloadAction<string>) => {
            state.streaming = false;
            state.error = action.payload;
            const last = state.messages[state.messages.length - 1];
            if (last && last.role === 'assistant' && !last.content) {
                last.content = `⚠️ ${action.payload}`;
            }
        },
    },
    extraReducers: (builder) => {
        builder
            .addCase(loadThread.pending, (state) => {
                state.loadingThread = true;
            })
            .addCase(loadThread.fulfilled, (state, action) => {
                state.loadingThread = false;
                state.threadId = action.payload.threadId;
                state.messages = action.payload.messages || [];
                state.totalUsage = action.payload.tokenUsage || EMPTY_USAGE;
                state.lastUsage = EMPTY_USAGE;
            })
            .addCase(loadThread.rejected, (state) => {
                // No thread yet — start fresh.
                state.loadingThread = false;
                state.messages = [];
                state.totalUsage = EMPTY_USAGE;
                state.lastUsage = EMPTY_USAGE;
            })
            .addCase(sendMessageStream.rejected, (state, action) => {
                state.streaming = false;
                state.error = action.error.message ?? 'Chat failed';
            });
    },
});

export const { openPanel, closePanel, togglePanel, setDate } = chatSlice.actions;
export default chatSlice.reducer;

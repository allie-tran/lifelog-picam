import { AppliedAction, ChatMemory, ChatThread, ChatTurnResponse, TokenUsage } from '@utils/types';
import axios from 'axios';
import { BACKEND_URL } from '../constants/urls';

export interface StreamDonePayload {
    threadId: string;
    appliedActions: AppliedAction[];
    messageUsage: TokenUsage;
    totalUsage: TokenUsage;
    distilled?: ChatMemory[];
}

export interface StreamHandlers {
    onDelta?: (text: string) => void;
    onTool?: (action: AppliedAction) => void;
    onDone?: (payload: StreamDonePayload) => void;
    onError?: (message: string) => void;
}

// Streams the assistant reply over SSE. Uses fetch (not axios) for a readable
// body; auth comes from the Authorization header axios already holds.
export const streamChatMessage = async (
    device: string,
    text: string,
    opts: { scope?: 'day' | 'global'; date?: string | null; threadId?: string } = {},
    handlers: StreamHandlers = {}
): Promise<void> => {
    const auth = (axios.defaults.headers.common['Authorization'] as string) || '';
    const res = await fetch(
        `${BACKEND_URL}/chat/message/stream?device=${encodeURIComponent(device)}`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: auth },
            body: JSON.stringify({
                text,
                scope: opts.scope ?? 'day',
                date: opts.date ?? null,
                threadId: opts.threadId ?? null,
            }),
        }
    );
    if (!res.ok || !res.body) {
        handlers.onError?.(`Chat failed (${res.status})`);
        return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    const handleEvent = (raw: string) => {
        const line = raw.split('\n').find((l) => l.startsWith('data:'));
        if (!line) return;
        let ev: any;
        try {
            ev = JSON.parse(line.slice(5).trim());
        } catch {
            return;
        }
        if (ev.type === 'delta') handlers.onDelta?.(ev.text);
        else if (ev.type === 'tool') handlers.onTool?.(ev.action);
        else if (ev.type === 'done') handlers.onDone?.(ev);
        else if (ev.type === 'error') handlers.onError?.(ev.message);
    };

    // eslint-disable-next-line no-constant-condition
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buffer.indexOf('\n\n')) !== -1) {
            handleEvent(buffer.slice(0, idx));
            buffer = buffer.slice(idx + 2);
        }
    }
    if (buffer.trim()) handleEvent(buffer);
};

export const sendChatMessage = async (
    device: string,
    text: string,
    opts: { scope?: 'day' | 'global'; date?: string | null; threadId?: string } = {}
): Promise<ChatTurnResponse> => {
    const response = await axios.post(
        `${BACKEND_URL}/chat/message?device=${encodeURIComponent(device)}`,
        {
            text,
            scope: opts.scope ?? 'day',
            date: opts.date ?? null,
            threadId: opts.threadId ?? null,
        }
    );
    return response.data as ChatTurnResponse;
};

export const getChatThread = async (device: string, threadId: string): Promise<ChatThread> => {
    const response = await axios.get(
        `${BACKEND_URL}/chat/thread/${encodeURIComponent(threadId)}?device=${encodeURIComponent(device)}`
    );
    return response.data as ChatThread;
};

export const getChatThreads = async (
    device: string,
    scope?: 'day' | 'global'
): Promise<ChatThread[]> => {
    const s = scope ? `&scope=${scope}` : '';
    const response = await axios.get(
        `${BACKEND_URL}/chat/threads?device=${encodeURIComponent(device)}${s}`
    );
    return response.data as ChatThread[];
};

export const getChatMemory = async (device: string): Promise<ChatMemory[]> => {
    const response = await axios.get(
        `${BACKEND_URL}/chat/memory?device=${encodeURIComponent(device)}`
    );
    return response.data as ChatMemory[];
};

export const putChatMemory = async (
    device: string,
    key: string,
    text: string
): Promise<ChatMemory> => {
    const response = await axios.put(
        `${BACKEND_URL}/chat/memory?device=${encodeURIComponent(device)}`,
        { key, text }
    );
    return response.data as ChatMemory;
};

export const deleteChatMemory = async (device: string, key: string) => {
    const response = await axios.delete(
        `${BACKEND_URL}/chat/memory/${encodeURIComponent(key)}?device=${encodeURIComponent(device)}`
    );
    return response.data;
};

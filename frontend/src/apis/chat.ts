import { ChatMemory, ChatThread, ChatTurnResponse } from '@utils/types';
import axios from 'axios';
import { BACKEND_URL } from '../constants/urls';

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

export const deleteChatMemory = async (device: string, key: string) => {
    const response = await axios.delete(
        `${BACKEND_URL}/chat/memory/${encodeURIComponent(key)}?device=${encodeURIComponent(device)}`
    );
    return response.data;
};

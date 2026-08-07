import axios from 'apis/defaultAxios';
import { BACKEND_URL } from '../constants/urls';

// Unified user feedback: ratings (thumbs), content flags, and free-text reports.
// Named `userFeedback` to avoid collision with the `feedback` UI-snackbar slice.

export type FeedbackKind = 'rating' | 'flag' | 'report';
export type FeedbackStatus = 'open' | 'reviewed' | 'resolved';

export type FeedbackRecord = {
    id: string;
    username: string;
    deviceId: string | null;
    kind: FeedbackKind;
    targetType: string | null;
    targetId: string | null;
    value: string | null;
    comment: string | null;
    meta: Record<string, unknown> | null;
    status: FeedbackStatus;
    createdAt: string | null;
    updatedAt: string | null;
};

export type SubmitFeedbackArgs = {
    kind: FeedbackKind;
    targetType?: string | null;
    targetId?: string | null;
    value?: string | null;   // 'up'/'down' for rating; reason slug for flag
    comment?: string | null;
    meta?: Record<string, unknown> | null;
    device?: string | null;  // context; required for rating/flag ownership check
};

// Submit any kind of feedback. Ratings upsert (value=null un-rates).
export const submitFeedback = async (args: SubmitFeedbackArgs) => {
    const params = args.device ? { device: args.device } : {};
    const response = await axios.post(
        `${BACKEND_URL}/feedback/submit`,
        {
            kind: args.kind,
            targetType: args.targetType ?? null,
            targetId: args.targetId ?? null,
            value: args.value ?? null,
            comment: args.comment ?? null,
            meta: args.meta ?? null,
        },
        { params }
    );
    return response.data;
};

// The caller's own ratings (to show active thumb state). Optionally by target type.
export const getMyFeedback = async (targetType?: string): Promise<FeedbackRecord[]> => {
    const response = await axios.get(`${BACKEND_URL}/feedback/mine`, {
        params: targetType ? { targetType } : {},
    });
    return response.data as FeedbackRecord[];
};

// Admin: list flags/reports (and ratings) for the review queue.
export const listFeedback = async (filters?: {
    kind?: FeedbackKind;
    status?: FeedbackStatus;
    limit?: number;
}): Promise<FeedbackRecord[]> => {
    const response = await axios.get(`${BACKEND_URL}/feedback/list`, {
        params: filters ?? {},
    });
    return response.data as FeedbackRecord[];
};

// Admin: move a flag/report through open → reviewed → resolved.
export const updateFeedbackStatus = async (
    feedbackId: string,
    status: FeedbackStatus
): Promise<FeedbackRecord> => {
    const response = await axios.patch(
        `${BACKEND_URL}/feedback/${feedbackId}/status`,
        { status }
    );
    return response.data as FeedbackRecord;
};

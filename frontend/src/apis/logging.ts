import axios from 'apis/defaultAxios';
import { BACKEND_URL } from 'constants/urls';

export type VBSCategory =
    | 'text'
    | 'image'
    | 'sketch'
    | 'filter'
    | 'browsing'
    | 'cooperation';

export interface VBSEvent {
    timestamp: number; // UNIX ms
    category: VBSCategory;
    type?: string;
    value?: string;
}

export interface VBSLogBatch {
    // DRES task context, so each event can be attributed to a task during
    // analysis (query→find time, per-task action funnel, etc.). Client is
    // identified server-side by IP — no team/member IDs sent.
    evaluationId?: string | null;
    taskName?: string | null;
    events: VBSEvent[];
}

export const postEvents = async (batch: VBSLogBatch) => {
    const res = await axios.post(`${BACKEND_URL}/log/event`, batch);
    return res.data as { written: number };
};

export interface SubmissionLog {
    submittedAt: number;
    evaluationId?: string | null;
    taskName?: string | null;
    contentType: 'image' | 'text';
    content?: string;
    verdict?: string;
}

export const postSubmission = async (sub: SubmissionLog) => {
    const res = await axios.post(`${BACKEND_URL}/log/submission`, sub);
    return res.data as { ok: boolean };
};

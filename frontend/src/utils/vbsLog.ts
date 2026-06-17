import { store } from 'reducers/store';
import { postEvents, postSubmission, VBSCategory, VBSEvent } from 'apis/logging';

// Shared gate: returns the DRES task context when logging is on, else null.
// The client is identified server-side by IP.
const logContext = (): { evaluationId: string | null; taskName: string | null } | null => {
    const state = store.getState();
    if (!state.vbsLog.enabled) return null;
    return {
        evaluationId: state.dres.evaluationId,
        taskName: state.dres.currentTask?.name ?? null,
    };
};

const warn = (e: unknown) => console.warn('VBS log failed', e); // never disrupt the UI

// Fire-and-forget VBS interaction logger. No-ops unless the toggle is on.
export const logEvent = (
    category: VBSCategory,
    type: string | undefined,
    value: string | undefined,
): void => {
    const ctx = logContext();
    if (!ctx) return;
    const event: VBSEvent = { timestamp: Date.now(), category, type, value };
    postEvents({ ...ctx, events: [event] }).catch(warn);
};

// Records a DRES submission + its verdict for query→find analysis.
export const logSubmission = (
    contentType: 'image' | 'text',
    content: string,
    verdict: string | undefined,
): void => {
    const ctx = logContext();
    if (!ctx) return;
    postSubmission({ ...ctx, submittedAt: Date.now(), contentType, content, verdict }).catch(warn);
};

import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { Task } from 'apis/dres';

interface DRESState {
    sessionId: string | null;
    evaluationId: string | null;
    currentTask: Task | null;
    submittedImages: string[];
}

const initialState: DRESState = {
    sessionId: null,
    evaluationId: null,
    currentTask: null,
    submittedImages: [],
};

const dresSlice = createSlice({
    name: 'dres',
    initialState,
    reducers: {
        dresLogin(state, action: PayloadAction<string>) {
            state.sessionId = action.payload;
            localStorage.setItem('dresSessionId', action.payload);
        },
        dresLogout(state) {
            state.sessionId = null;
            state.evaluationId = null;
            state.currentTask = null;
            localStorage.removeItem('dresSessionId');
        },
        setEvaluation(state, action: PayloadAction<string>) {
            state.evaluationId = action.payload;
            state.currentTask = null;
        },
        setCurrentTask(state, action: PayloadAction<Task | null>) {
            state.currentTask = action.payload;
        },
        addSubmittedImages(state, action: PayloadAction<string[]>) {
            const set = new Set(state.submittedImages);
            action.payload.forEach((p) => set.add(p));
            state.submittedImages = Array.from(set);
        },
        clearSubmittedImages(state) {
            state.submittedImages = [];
        },
    },
});

export const { dresLogin, dresLogout, setEvaluation, setCurrentTask, addSubmittedImages, clearSubmittedImages } = dresSlice.actions;
export default dresSlice.reducer;

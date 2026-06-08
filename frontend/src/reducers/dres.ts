import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { Task } from 'apis/dres';

interface DRESState {
    sessionId: string | null;
    evaluationId: string | null;
    currentTask: Task | null;
}

const initialState: DRESState = {
    sessionId: null,
    evaluationId: null,
    currentTask: null,
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
    },
});

export const { dresLogin, dresLogout, setEvaluation, setCurrentTask } = dresSlice.actions;
export default dresSlice.reducer;

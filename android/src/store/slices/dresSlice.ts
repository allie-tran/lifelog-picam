import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { SubmitVerdict } from '../../api/dres';

interface Task {
  name: string;
  taskGroup: string;
  taskType: string;
  duration: number;
}

export interface SubmissionRecord {
  type: 'image' | 'text';
  content: string;
  verdict: SubmitVerdict;
  message: string;
  ts: string;
}

interface DRESState {
  sessionId: string | null;
  evaluationId: string | null;
  currentTask: Task | null;
  submissions: SubmissionRecord[];
}

const dresSlice = createSlice({
  name: 'dres',
  initialState: {
    sessionId: null,
    evaluationId: null,
    currentTask: null,
    submissions: [],
  } as DRESState,
  reducers: {
    dresLogin(state, action: PayloadAction<string>) {
      state.sessionId = action.payload;
    },
    dresLogout(state) {
      state.sessionId = null;
      state.evaluationId = null;
      state.currentTask = null;
      state.submissions = [];
    },
    setEvaluation(state, action: PayloadAction<string>) {
      state.evaluationId = action.payload;
      state.currentTask = null;
    },
    setCurrentTask(state, action: PayloadAction<Task | null>) {
      state.currentTask = action.payload;
    },
    addSubmission(state, action: PayloadAction<SubmissionRecord>) {
      state.submissions = [action.payload, ...state.submissions].slice(0, 50);
    },
    clearSubmissions(state) {
      state.submissions = [];
    },
  },
});

export const {
  dresLogin,
  dresLogout,
  setEvaluation,
  setCurrentTask,
  addSubmission,
  clearSubmissions,
} = dresSlice.actions;
export default dresSlice.reducer;

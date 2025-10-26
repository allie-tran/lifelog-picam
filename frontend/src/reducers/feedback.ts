import { createSlice, PayloadAction } from '@reduxjs/toolkit';

interface NotificationPayload {
    message: string;
    type: 'info' | 'warning' | 'error' | 'success';
}

interface FeedbackState {
    notification: NotificationPayload | null;
    loading: boolean;
}

const initialState: FeedbackState = {
    notification: null,
    loading: false,
};

export const feedbackSlice = createSlice({
    name: 'feedback',
    initialState,
    reducers: {
        showNotification: (state, action: PayloadAction<NotificationPayload>) => {
            state.notification = action.payload;
        },
        hideNotification: (state) => {
            state.notification = null;
        },
        setLoading: (state, action: PayloadAction<boolean>) => {
            state.loading = action.payload;
        },
    },
});

export const { showNotification, hideNotification, setLoading } = feedbackSlice.actions;
export default feedbackSlice.reducer;


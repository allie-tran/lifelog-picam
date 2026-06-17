import { createSlice, PayloadAction } from '@reduxjs/toolkit';

// Frontend gate for VBS interaction logging. When `enabled`, query/browse
// actions and DRES submissions are POSTed to the backend and persisted. The
// client is identified server-side by IP, so no team/member IDs are kept here.
interface VBSLogState {
    enabled: boolean;
}

const ENABLED_KEY = 'vbsLogEnabled';

const initialState: VBSLogState = {
    enabled: localStorage.getItem(ENABLED_KEY) === 'true',
};

const vbsLogSlice = createSlice({
    name: 'vbsLog',
    initialState,
    reducers: {
        setVbsLogEnabled(state, action: PayloadAction<boolean>) {
            state.enabled = action.payload;
            localStorage.setItem(ENABLED_KEY, String(action.payload));
        },
    },
});

export const { setVbsLogEnabled } = vbsLogSlice.actions;
export default vbsLogSlice.reducer;

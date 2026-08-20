import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { UIMode } from 'types/auth';

interface UIState {
    // Which UI tier to render. Hydrated from the user document on login; the
    // backend is the source of truth, this mirror just drives conditional render.
    mode: UIMode;
}

const initialState: UIState = {
    mode: UIMode.SIMPLE,
};

const uiSlice = createSlice({
    name: 'ui',
    initialState,
    reducers: {
        setUIMode(state, action: PayloadAction<UIMode>) {
            state.mode = action.payload;
        },
    },
});

export const { setUIMode } = uiSlice.actions;
export default uiSlice.reducer;

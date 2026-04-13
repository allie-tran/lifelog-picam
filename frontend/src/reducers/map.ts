import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { GPSData } from 'utils/types';


interface FeedbackState {
    highlightedTrack: GPSData[];
}

const initialState: FeedbackState = {
    highlightedTrack: [],
};

export const mapSlice = createSlice({
    name: 'map',
    initialState,
    reducers: {
        setHighlightedTrack: (state, action: PayloadAction<GPSData[]>) => {
            state.highlightedTrack = action.payload;
        }
    },
});

export const { setHighlightedTrack } = mapSlice.actions;
export default mapSlice.reducer;


import { createSlice, PayloadAction } from '@reduxjs/toolkit';

interface ZoomedImageState {
    image: string;
    isVideo: boolean;
}

const initialState: ZoomedImageState = {
    image: '',
    isVideo: false,
};

export const zoomedImageSlice = createSlice({
    name: 'zoomedImage',
    initialState,
    reducers: {
        setZoomedImage: (state, action: PayloadAction<ZoomedImageState>) => {
            console.log('Zoomed image set to:', state.image);
            state.image = action.payload.image;
            state.isVideo = action.payload.isVideo;
        },
        clearZoomedImage: (state) => {
            state.image = '';
            state.isVideo = false;
        },
    },
});

export const { setZoomedImage, clearZoomedImage } = zoomedImageSlice.actions;
export default zoomedImageSlice.reducer;

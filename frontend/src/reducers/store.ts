import { configureStore } from '@reduxjs/toolkit';
import zoomedImageSlice from './zoomedImage';
import feedbackSlice from './feedback';
import authSlice from './auth';
import mapSlice from './map';
import searchSlice from './search';
import dresSlice from './dres';
import notificationsSlice from './notifications';

export const store = configureStore({
    reducer: {
        zoomedImage: zoomedImageSlice,
        feedback: feedbackSlice,
        search: searchSlice,
        auth: authSlice,
        map: mapSlice,
        dres: dresSlice,
        notifications: notificationsSlice,
    },
});

// Infer the `RootState` and `AppDispatch` types from the store itself
export type RootState = ReturnType<typeof store.getState>;
// Inferred type: {posts: PostsState, comments: CommentsState, users: UsersState}
export type AppDispatch = typeof store.dispatch;

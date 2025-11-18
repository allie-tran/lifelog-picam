import { configureStore } from '@reduxjs/toolkit';
import zoomedImageSlice from './zoomedImage';
import feedbackSlice from './feedback';
import authSlice from './auth';

export const store = configureStore({
    reducer: {
        zoomedImage: zoomedImageSlice,
        feedback: feedbackSlice,
        auth: authSlice,
    },
});

// Infer the `RootState` and `AppDispatch` types from the store itself
export type RootState = ReturnType<typeof store.getState>;
// Inferred type: {posts: PostsState, comments: CommentsState, users: UsersState}
export type AppDispatch = typeof store.dispatch;

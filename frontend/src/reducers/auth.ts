import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { DeviceAccess } from 'types/auth';


interface AuthState {
    isAuthenticated: boolean;
    username: string | null;
    devices: DeviceAccess[];
    deviceId?: string | null;
}

const initialState: AuthState = {
    isAuthenticated: false,
    username: null,
    devices: [],
    deviceId: "allie",
};

const authSlice = createSlice({
    name: 'auth',
    initialState,
    reducers: {
        login(state, action: PayloadAction<{ username: string; devices: DeviceAccess[] }>) {
            state.isAuthenticated = true;
            state.username = action.payload.username;
            state.devices = action.payload.devices;
        },
        logout(state) {
            state.isAuthenticated = false;
            state.username = null;
            state.devices = [];
        },
        setDeviceId(state, action: PayloadAction<string | null>) {
            state.deviceId = action.payload;
        }
    },
});

export const { login, logout, setDeviceId } = authSlice.actions;
export default authSlice.reducer;

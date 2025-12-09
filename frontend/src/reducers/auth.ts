import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { AccessLevel, DeviceAccess } from 'types/auth';


interface AuthState {
    isAuthenticated: boolean;
    username: string | null;
    devices: DeviceAccess[];
    deviceId: string;
    deviceAccess: AccessLevel;
}

const initialState: AuthState = {
    isAuthenticated: false,
    username: null,
    devices: [],
    deviceId: "allie",
    deviceAccess: AccessLevel.NONE,
};

const authSlice = createSlice({
    name: 'auth',
    initialState,
    reducers: {
        login(state, action: PayloadAction<{ username: string; devices: DeviceAccess[] }>) {
            state.isAuthenticated = true;
            state.username = action.payload.username;
            state.devices = action.payload.devices;
            state.deviceAccess = action.payload.devices?.find(device => device.deviceId === state.deviceId)?.accessLevel || AccessLevel.NONE
        },
        logout(state) {
            state.isAuthenticated = false;
            state.username = null;
            state.devices = [];
        },
        setDeviceId(state, action: PayloadAction<string>) {
            state.deviceId = action.payload;
            state.deviceAccess = state.devices?.find(device => device.deviceId === state.deviceId)?.accessLevel || AccessLevel.NONE;
        }
    },
});

export const { login, logout, setDeviceId } = authSlice.actions;
export default authSlice.reducer;

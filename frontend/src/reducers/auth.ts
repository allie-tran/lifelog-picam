import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { AccessLevel, DeviceAccess, SensorDevice } from 'types/auth';


interface AuthState {
    isAuthenticated: boolean;
    username: string | null;
    devices: DeviceAccess[];
    device: string;
    deviceAccess: AccessLevel;
    sensors: SensorDevice[];
}

const initialState: AuthState = {
    isAuthenticated: false,
    username: null,
    devices: [],
    device: "",
    deviceAccess: AccessLevel.NONE,
    sensors: [],
};

const authSlice = createSlice({
    name: 'auth',
    initialState,
    reducers: {
        login(state, action: PayloadAction<{ username: string; devices: DeviceAccess[], sensors: SensorDevice[] }>) {
            state.isAuthenticated = true;
            state.username = action.payload.username;
            state.devices = action.payload.devices;
            state.deviceAccess = action.payload.devices?.find(d => d.deviceId === state.device)?.accessLevel || AccessLevel.NONE
            state.sensors = action.payload.sensors;
        },
        logout(state) {
            state.isAuthenticated = false;
            state.username = null;
            state.devices = [];
        },
        setDevice(state, action: PayloadAction<string>) {
            state.device = action.payload;
            state.deviceAccess = state.devices?.find(d => d.deviceId === state.device)?.accessLevel || AccessLevel.NONE;
        }
    },
});

export const { login, logout, setDevice } = authSlice.actions;
export default authSlice.reducer;

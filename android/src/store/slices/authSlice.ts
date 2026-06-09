import { createSlice, PayloadAction } from '@reduxjs/toolkit';

interface AuthState {
  isAuthenticated: boolean;
  username: string;
  token: string | null;
  deviceId: string;
  devices: string[];
}

const initialState: AuthState = {
  isAuthenticated: false,
  username: '',
  token: null,
  deviceId: '',
  devices: [],
};

const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    login(state, action: PayloadAction<{ username: string; token: string; devices: string[] }>) {
      state.isAuthenticated = true;
      state.username = action.payload.username;
      state.token = action.payload.token;
      state.devices = action.payload.devices;
      if (action.payload.devices.length > 0 && !state.deviceId) {
        state.deviceId = action.payload.devices[0];
      }
    },
    logout(state) {
      state.isAuthenticated = false;
      state.username = '';
      state.token = null;
    },
    setDeviceId(state, action: PayloadAction<string>) {
      state.deviceId = action.payload;
    },
  },
});

export const { login, logout, setDeviceId } = authSlice.actions;
export default authSlice.reducer;

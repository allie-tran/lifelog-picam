import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';

const DEFAULT_BACKEND_URL = 'http://10.0.2.2:8082';

// Mutable config — mutate this object rather than the binding so all
// module consumers see the updated value immediately (object reference is stable).
export const config = {
  backendUrl: DEFAULT_BACKEND_URL,
};

export const axiosInstance = axios.create({ baseURL: DEFAULT_BACKEND_URL });

axiosInstance.interceptors.request.use(async cfg => {
  const token = await AsyncStorage.getItem('token');
  if (token) cfg.headers.Authorization = `Bearer ${token}`;
  return cfg;
});

export const setBackendUrl = async (url: string) => {
  const clean = url.replace(/\/$/, ''); // strip trailing slash
  config.backendUrl = clean;
  axiosInstance.defaults.baseURL = clean;
  await AsyncStorage.setItem('backendUrl', clean);
};

export const loadBackendUrl = async () => {
  const saved = await AsyncStorage.getItem('backendUrl');
  if (saved) {
    config.backendUrl = saved;
    axiosInstance.defaults.baseURL = saved;
  }
};

// Warm palette matching the webapp theme
export const COLORS = {
  primary: '#FF9E7D',
  secondary: '#16A299',
  background: '#FDFCF0',
  surface: 'rgba(255, 255, 255, 0.95)',
  textPrimary: '#2D3436',
  textSecondary: '#636E72',
  divider: '#DFE6E9',
  success: '#A8E6CF',
  error: '#FF7675',
  purple: '#8E44AD',
};

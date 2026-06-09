import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';

const DEFAULT_BACKEND_URL = 'https://dcu.allietran.com/selfhealth/be';
const DEFAULT_IMAGE_URL = 'https://dcu.allietran.com/images/LifelogPicam';
const DEFAULT_TIMEZONE = 'Europe/Dublin';

// Mutable config — mutate this object rather than the binding so all
// module consumers see the updated value immediately (object reference is stable).
export const config = {
  backendUrl: DEFAULT_BACKEND_URL,
  imageUrl: DEFAULT_IMAGE_URL,
  defaultTimezone: DEFAULT_TIMEZONE,
};

export const axiosInstance = axios.create({ baseURL: DEFAULT_BACKEND_URL });

axiosInstance.interceptors.request.use(async cfg => {
  const token = await AsyncStorage.getItem('token');
  if (token) cfg.headers.Authorization = `Bearer ${token}`;
  return cfg;
});

export const setBackendUrl = async (url: string) => {
  const clean = url.replace(/\/$/, '');
  config.backendUrl = clean;
  axiosInstance.defaults.baseURL = clean;
  await AsyncStorage.setItem('backendUrl', clean);
};

export const setImageUrl = async (url: string) => {
  const clean = url.replace(/\/$/, '');
  config.imageUrl = clean;
  await AsyncStorage.setItem('imageUrl', clean);
};

export const loadBackendUrl = async () => {
  const savedBackend = await AsyncStorage.getItem('backendUrl');
  if (savedBackend) {
    config.backendUrl = savedBackend;
    axiosInstance.defaults.baseURL = savedBackend;
  }
  const savedImage = await AsyncStorage.getItem('imageUrl');
  if (savedImage) {
    config.imageUrl = savedImage;
  }
};

// Timestamps from the backend are naive UTC (no Z suffix). Without the Z,
// new Date() treats the string as local device time. Force UTC parsing.
const toUTCDate = (timestamp: string | number): Date => {
  if (typeof timestamp === 'string' && !/[Zz]|[+-]\d{2}:?\d{2}$/.test(timestamp)) {
    return new Date(timestamp + 'Z');
  }
  return new Date(timestamp);
};

// Hermes's Intl.DateTimeFormat.formatToParts returns the right timeZoneName
// but does not convert hour/minute to the target timezone. toLocaleString goes
// through a different code path that correctly applies the offset.
export const formatTimeTz = (timestamp: string | number, tz: string): string => {
  try {
    const date = toUTCDate(timestamp);
    const tzName = new Intl.DateTimeFormat('en-GB', { timeZone: tz, timeZoneName: 'short' })
      .formatToParts(date)
      .find(p => p.type === 'timeZoneName')?.value ?? '';
    const time = date.toLocaleString('en-GB', { timeZone: tz, hour: '2-digit', minute: '2-digit', hour12: false });
    return `${time} ${tzName}`.trim();
  } catch {
    const d = toUTCDate(timestamp);
    return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`;
  }
};

export const formatDateTimeTz = (timestamp: string | number, tz: string): string => {
  try {
    const date = toUTCDate(timestamp);
    const tzName = new Intl.DateTimeFormat('en-GB', { timeZone: tz, timeZoneName: 'short' })
      .formatToParts(date)
      .find(p => p.type === 'timeZoneName')?.value ?? '';
    const time = date.toLocaleString('en-GB', { timeZone: tz, hour: '2-digit', minute: '2-digit', hour12: false });
    const datePart = date.toLocaleString('en-GB', { timeZone: tz, day: 'numeric', month: 'short', year: 'numeric' });
    return `${time} · ${datePart} ${tzName}`.trim();
  } catch {
    const d = toUTCDate(timestamp);
    return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`;
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

import { axiosInstance } from '../constants';
import { LocationData } from '../types';

export const getLocations = (deviceId: string, countries: string[]) =>
  axiosInstance.post<LocationData[]>(
    `/explore/get-locations?device=${encodeURIComponent(deviceId)}`,
    { field: 'location', extraParams: { country: countries } },
  );

export const getMovingPeriods = (deviceId: string, countries: string[]) =>
  axiosInstance.post<LocationData[]>(
    `/explore/get-moving-periods?device=${encodeURIComponent(deviceId)}`,
    { field: 'location', extraParams: { country: countries } },
  );

export const searchLocations = (deviceId: string, q: string, limit = 20) =>
  axiosInstance.get<LocationData[]>(`/explore/search-locations`, {
    params: { device: deviceId, q, limit },
  });

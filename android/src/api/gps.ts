import { axiosInstance } from '../constants';

export interface GPSPoint {
  latitude: number;
  longitude: number;
  elevation?: number;
  timestamp: string;
  timezone?: string;
}

export const sendGPS = async (
  lat: number,
  lon: number,
  elevation: number,
  deviceId: string,
  time: string,
) => {
  const res = await axiosInstance.put('/location/upload-gps', {
    latitude: lat,
    longitude: lon,
    elevation,
    timestamp: time,
    deviceId,
  });
  return res.data;
};

export const processGPS = async (device: string, date: string) => {
  const res = await axiosInstance.get(
    `/location/process-gps?device=${device}&date=${date}`,
  );
  return res.data;
};

export const getGPSByDate = async (
  date: string,
  device: string,
): Promise<GPSPoint[]> => {
  const res = await axiosInstance.get(
    `/location/get-gps-by-date?date=${date}&device=${device}`,
  );
  return res.data;
};

export const getLatestGPS = async (device: string): Promise<GPSPoint> => {
  const res = await axiosInstance.get(`/location/latest-gps?device=${device}`);
  return res.data;
};

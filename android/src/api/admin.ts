import { axiosInstance } from '../constants';

export interface DeviceAccess {
  deviceId: string;
  accessLevel: string;
}

export interface SensorDevice {
  deviceId: string;
  sensorType: string;
  deviceNickname: string;
  secret?: string;
}

export interface UserInfo {
  username: string;
  devices?: DeviceAccess[];
  sensors?: SensorDevice[];
}

export interface MeasurementRecord {
  timeStamp: number;
  values: Record<string, number | null>;
}

export const getUsers = () =>
  axiosInstance.get<UserInfo[]>('/auth/users');

export const changeUserAccess = (
  username: string,
  deviceId: string,
  accessLevel: string,
) =>
  axiosInstance.post('/auth/change-access', { username, deviceId, accessLevel });

export const addSensorToUser = (
  deviceId: string,
  sensorType: string,
  sensorSecret: string,
  deviceNickname: string,
  associatedUsername: string,
) =>
  axiosInstance.put('/auth/add-sensor', {
    deviceId,
    sensorType,
    secret: sensorSecret,
    deviceNickname,
    associatedUsername,
  });

export const getSensorLogs = (
  sensor: string,
  date: string,
  deviceId: string,
) =>
  axiosInstance.get<{ keys: string[]; logs: Record<string, MeasurementRecord[]> }>(
    `/browse/logs/${sensor}?date=${date}&device_id=${encodeURIComponent(deviceId)}`,
  );

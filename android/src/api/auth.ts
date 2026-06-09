import { axiosInstance } from '../constants';

export const loginRequest = (username: string, password: string) =>
  axiosInstance.post('/auth/login', { username, password });

export const registerRequest = (username: string, password: string) =>
  axiosInstance.post('/auth/register', { username, password });

export const verifyTokenRequest = (token: string) =>
  axiosInstance.post('/auth/verify', { token });

export const getDevices = () =>
  axiosInstance.get<string[]>('/get-devices');

import { axiosInstance } from '../constants';

export const addFaceToWhitelist = (deviceId: string, name: string, imageUris: string[]) => {
  const formData = new FormData();
  imageUris.slice(0, 3).forEach((uri, i) => {
    formData.append('files', { uri, type: 'image/jpeg', name: `face_${i}.jpg` } as any);
  });
  return axiosInstance.post(
    `/face/add-to-whitelist?device=${encodeURIComponent(deviceId)}&name=${encodeURIComponent(name)}`,
    formData,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  );
};

export const removeFaceFromWhitelist = (deviceId: string, name: string) =>
  axiosInstance.delete(
    `/face/remove-from-whitelist?device=${encodeURIComponent(deviceId)}&name=${encodeURIComponent(name)}`,
  );

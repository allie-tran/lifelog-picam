import { axiosInstance } from '../constants';
import { DaySummary, ImageObject, SearchQuery, SearchResult } from '../types';

export const getAllDates = (deviceId: string) =>
  axiosInstance.get<string[]>(`/get-all-dates?device=${encodeURIComponent(deviceId)}`);

export const getImagesByHour = (deviceId: string, date: string, hour: number, page = 1) =>
  axiosInstance.get(`/browse/get-images-by-hour?date=${date}&hour=${hour}&page=${page}&device=${encodeURIComponent(deviceId)}`);

export const searchImages = (deviceId: string, query: SearchQuery, sortBy: 'time' | 'relevance' = 'relevance') =>
  axiosInstance.post<SearchResult>(
    `/retrieval/search-images?device=${encodeURIComponent(deviceId)}&sort_by=${sortBy}`,
    query,
  );

export const deleteImage = (deviceId: string, imagePath: string) =>
  axiosInstance.delete(`/delete/delete-image?device=${encodeURIComponent(deviceId)}`, {
    data: { imagePath },
  });

export const parseQueryFilters = (text: string, deviceId?: string) => {
  const param = deviceId ? `&device=${encodeURIComponent(deviceId)}` : '';
  return axiosInstance.get(`/retrieval/parse-query?text=${encodeURIComponent(text)}${param}`);
};

export const getAllFaces = (deviceId: string) =>
  axiosInstance.get<{ name: string; images: string[]; id: string }[]>(
    `/explore/all-faces?device=${encodeURIComponent(deviceId)}`,
  );

export const getAvailableValues = (deviceId: string, field: string) =>
  axiosInstance.get<string[]>(
    `/explore/available-values?device=${encodeURIComponent(deviceId)}&field=${field}`,
  );

export const processDate = (deviceId: string, date: string, resegment: boolean, reannotate: boolean) =>
  axiosInstance.get(
    `/process-date?date=${encodeURIComponent(date)}&device=${encodeURIComponent(deviceId)}&resegment=${resegment}&reannotate=${reannotate}`,
  );

export const changeSegmentActivity = (deviceId: string, date: string, segmentId: number, newActivityInfo: string) =>
  axiosInstance.post(
    `/change-segment-activity?device=${encodeURIComponent(deviceId)}`,
    { date, segmentId, newActivityInfo },
  );

export const getDaySummary = (deviceId: string, date: string) =>
  axiosInstance.get<DaySummary>(
    `/day-summary?date=${encodeURIComponent(date)}&device=${encodeURIComponent(deviceId)}`,
  );

export const similarImages = (deviceId: string, imagePath: string) =>
  axiosInstance.get<ImageObject[]>(
    `/retrieval/similar-images?image=${encodeURIComponent(imagePath)}&device=${encodeURIComponent(deviceId)}`,
  );

export const getDeletedImages = (deviceId: string) =>
  axiosInstance.get<ImageObject[]>(`/delete/get-deleted-images?device=${encodeURIComponent(deviceId)}`);

export const restoreImage = (deviceId: string, imagePath: string) =>
  axiosInstance.post(`/delete/restore-image?device=${encodeURIComponent(deviceId)}`, { imagePath });

export const forceDeleteImage = (deviceId: string, imagePath: string) =>
  axiosInstance.delete(`/delete/force-delete-image?device=${encodeURIComponent(deviceId)}`, {
    data: { imagePath },
  });

export const forceDeleteImages = (deviceId: string, imagePaths: string[]) =>
  axiosInstance.delete(`/delete/force-delete-images?device=${encodeURIComponent(deviceId)}`, {
    data: { imagePaths },
  });

export const deleteImages = (deviceId: string, imagePaths: string[]) =>
  axiosInstance.delete(`/delete/delete-images?device=${encodeURIComponent(deviceId)}`, {
    data: { imagePaths },
  });

export interface ImageMetadata {
  imagePath: string;
  timestamp: string;
  timezone: string;
  gps?: { latitude: number; longitude: number } | null;
  location?: { name?: string; address?: string; country?: string } | null;
  objects: { label: string; confidence: number; bbox: number[] }[];
  people: { label: string; confidence: number; bbox: number[]; clusterId?: string | null; clusterName?: string | null }[];
}

export const getImageMetadata = (deviceId: string, imagePath: string) =>
  axiosInstance.get<ImageMetadata>(
    `/browse/get-image?device=${encodeURIComponent(deviceId)}&filename=${encodeURIComponent(imagePath)}`,
  );

export interface GpsPoint {
  latitude: number;
  longitude: number;
  elevation?: number;
}

export const getGpsByDate = (deviceId: string, date: string) =>
  axiosInstance.get<GpsPoint[]>(
    `/location/get-gps-by-date?date=${encodeURIComponent(date)}&device=${encodeURIComponent(deviceId)}`,
  );

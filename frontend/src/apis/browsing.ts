import axios from 'axios';
import { BACKEND_URL } from '../constants/urls';
import { ImageObject } from '@utils/types';
import { getCookie, parseErrorResponse } from 'utils/misc';

axios.defaults.headers.common['Authorization'] = `Bearer ${getCookie('token')}`;
axios.interceptors.request.use(
    function (config) {
        const token = getCookie('token');
        if (token) {
            config.headers['Authorization'] = `Bearer ${token}`;
        }
        return config;
    },
    function (error: any) {
        console.error('There was an error setting auth header!', error);
        alert(parseErrorResponse(error.response));
        return Promise.reject(error);
    }
);

export const getDevices = async () => {
    const response = await axios.get(`${BACKEND_URL}/get-devices`);
    return response.data as string[];
};

export const getImages = async (
    page: number = 1,
    device: string | null = null,
    date: string | null = null
) => {
    const response = await axios.get(
        `${BACKEND_URL}/get-images?page=${page}${date ? `&date=${date}` : ''}${device ? `&device=${encodeURIComponent(device)}` : ''}`
    );
    return response.data as {
        date: string;
        images: ImageObject[];
        total_pages: number;
    };
};

export const getImagesByHour = async (
    device: string,
    date: string,
    hour: number,
    page: number = 1
) => {
    const response = await axios.get(
        `${BACKEND_URL}/get-images-by-hour?date=${date}&hour=${hour}&page=${page}&device=${encodeURIComponent(device)}`
    );
    return response.data as {
        date: string;
        hour: number;
        images: ImageObject[];
        segments: ImageObject[][];
        available_hours: number[];
        total_pages: number;
    };
};

export const getImage = async (deviceId: string, filename: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/get-image?filename=${encodeURIComponent(filename)}&device=${encodeURIComponent(deviceId)}`
    );
    const imageBase64 = response.data;
    return imageBase64 as string;
};

export const getAllDates = async (deviceId: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/get-all-dates?device=${encodeURIComponent(deviceId)}`
    );
    return response.data as string[];
};

export const searchImages = async (
    deviceId: string,
    query: string,
    sortBy: 'time' | 'relevance' = 'time'
) => {
    const response = await axios.get(
        `${BACKEND_URL}/search-images?query=${query}&device=${encodeURIComponent(deviceId)}&sort_by=${sortBy}`
    );
    return response.data as ImageObject[][];
};

export const similarImages = async (deviceId: string, imagePath: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/similar-images?image=${encodeURIComponent(imagePath)}&device=${encodeURIComponent(deviceId)}`
    );
    return response.data as ImageObject[];
};

export const similarImagesPost = async (deviceId: string, blobUrl: string) => {
    const formData = new FormData();
    const blobResponse = await fetch(blobUrl);
    const blob = await blobResponse.blob();
    formData.append('file', blob, 'query_image');

    const response = await axios.post(
        `${BACKEND_URL}/similar-images?device=${encodeURIComponent(deviceId)}`,
        formData,
        {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        }
    );
    return response.data as ImageObject[];
};

export const deleteImage = async (deviceId: string, imagePath: string) => {
    const response = await axios.delete(
        `${BACKEND_URL}/delete-image?device=${encodeURIComponent(deviceId)}`,
        {
            data: { imagePath },
        }
    );
    return response.data;
};

export const getDeletedImages = async (deviceId: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/get-deleted-images?device=${encodeURIComponent(deviceId)}`
    );
    return response.data as ImageObject[];
};

export const restoreImage = async (deviceId: string, imagePath: string) => {
    const response = await axios.post(
        `${BACKEND_URL}/restore-image?device=${encodeURIComponent(deviceId)}`,
        {
            imagePath,
        }
    );
    return response.data;
};

export const forceDeleteImage = async (deviceId: string, imagePath: string) => {
    const response = await axios.delete(
        `${BACKEND_URL}/force-delete-image?device=${encodeURIComponent(deviceId)}`,
        {
            data: { imagePath },
        }
    );
    return response.data;
};

import axios from 'axios';
import { BACKEND_URL } from '../constants/urls';
import { ActionType, CustomGoal, ImageObject, Point } from 'utils/types';
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

export const getImagesByRange = async (
    device: string,
    date: string,
    startTime: number,
    endTime: number
) => {
    const response = await axios.post(
        `${BACKEND_URL}/get-images-by-range?device=${encodeURIComponent(device)}`,
        {
            start_time: startTime,
            date: date,
            end_time: endTime,
        }
    );
    return response.data as ImageObject[];
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

export const deleteImages = async (deviceId: string, imagePaths: string[]) => {
    const response = await axios.delete(
        `${BACKEND_URL}/delete-images?device=${encodeURIComponent(deviceId)}`,
        {
            data: { imagePaths },
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

export const forceDeleteImages = async (
    deviceId: string,
    imagePaths: string[]
) => {
    const response = await axios.delete(
        `${BACKEND_URL}/force-delete-images?device=${encodeURIComponent(deviceId)}`,
        {
            data: { imagePaths },
        }
    );
    return response.data;
};

export const getUserGoals = async (deviceId: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/get-targets?device=${encodeURIComponent(deviceId)}`
    );
    let goals: CustomGoal[] = [];
    for (const goal of response.data) {
        goals.push({
            name: goal[0],
            type: goal[1] as ActionType,
            query_prompt: goal[2] || '',
        });
    }
    return goals;
};

export const updateUserGoals = async (
    goals: CustomGoal[],
    deviceId: string
) => {
    const response = await axios.post(
        `${BACKEND_URL}/update-targets?device=${encodeURIComponent(deviceId)}`,
        goals.map((goal) => [goal.name, goal.type, goal.query_prompt || ''])
    );
    return response.data;
};

export const getFaces = async (deviceId: string, blobUrls: string[]) => {
    const formData = new FormData();
    for (let i = 0; i < blobUrls.length; i++) {
        const blobResponse = await fetch(blobUrls[i]);
        const blob = await blobResponse.blob();
        formData.append('files', blob, `face_image_${i}`);
    }
    const response = await axios.post(
        `${BACKEND_URL}/get-faces?device=${encodeURIComponent(deviceId)}`,
        formData,
        {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        }
    );
    return response.data as ImageObject[];
};

export const addToWhiteList = async (
    deviceId: string,
    blobUrls: string[],
    name: string
) => {
    const formData = new FormData();
    for (let i = 0; i < blobUrls.length; i++) {
        const blobResponse = await fetch(blobUrls[i]);
        const blob = await blobResponse.blob();
        formData.append('files', blob, `white_list_image_${i}`);
    }
    const response = await axios.put(
        `${BACKEND_URL}/add-to-whitelist?device=${encodeURIComponent(deviceId)}&name=${name}`,
        formData,
        {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        }
    );
    return response.data;
};

export const getWhiteList = async (deviceId: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/get-whitelist?device=${encodeURIComponent(deviceId)}`
    );
    return response.data as { name: string; images: string[] }[];
};

export const removeFromWhiteList = async (deviceId: string, name: string) => {
    const response = await axios.delete(
        `${BACKEND_URL}/remove-from-whitelist?device=${encodeURIComponent(deviceId)}&name=${name}`
    );
    return response.data;
};

export const uploadAndSegment = async (blobUrl: string, points: Point[]) => {
    const formData = new FormData();
    const blobResponse = await fetch(blobUrl);
    const blob = await blobResponse.blob();
    formData.append('file', blob, 'segment_image');
    formData.append('points', JSON.stringify(points.map((p) => [p.x, p.y])));

    try {
        const response = await axios.post(
            `${BACKEND_URL}/segment-image`,
            formData,
            {
                headers: { 'Content-Type': 'multipart/form-data' },
            }
        );
        return response.data as string;
    } catch (error) {
        console.error('Segmentation failed', error);
    }
};

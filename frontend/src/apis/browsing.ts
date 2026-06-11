import axios from 'apis/defaultAxios';
import {
    ActionType,
    CustomGoal,
    GPSData,
    ImageObject,
    ImageWithMetadata,
    Point,
    ResultSegment,
    SearchQuery,
} from 'utils/types';
import { BACKEND_URL } from '../constants/urls';

export const getDevices = async () => {
    const response = await axios.get(`${BACKEND_URL}/get-devices`);
    return response.data as string[];
};


export const getImagesByHour = async (
    device: string,
    date: string,
    hour: number,
    page: number = 1
) => {
    const response = await axios.get(
        `${BACKEND_URL}/browse/get-images-by-hour?date=${date}&hour=${hour}&page=${page}&device=${encodeURIComponent(device)}`
    );
    return response.data as {
        date: string;
        hour: number;
        images: ImageObject[];
        segments: ResultSegment[];
        available_hours: number[];
        total_pages: number;
        gps: GPSData[];
    };
};

export const getImagesByRange = async (
    device: string,
    date: string,
    startTime: number,
    endTime: number
) => {
    const response = await axios.post(
        `${BACKEND_URL}/browse/get-images-by-range?device=${encodeURIComponent(device)}`,
        {
            start_time: startTime,
            date: date,
            end_time: endTime,
        }
    );
    return response.data as ImageObject[];
};

export const getContextImages = async (device: string, imagePath: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/browse/get-context-images?device=${encodeURIComponent(device)}&image=${encodeURIComponent(imagePath)}`
    );
    return response.data as ResultSegment[];
};

export const getImage = async (device: string, filename: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/browse/get-image?filename=${encodeURIComponent(filename)}&device=${encodeURIComponent(device)}`
    );
    return response.data as ImageWithMetadata;
};

export const getAllDates = async (device: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/get-all-dates?device=${encodeURIComponent(device)}`
    );
    return response.data as string[];
};

export const parseQueryFilters = async (text: string, device?: string): Promise<Partial<SearchQuery>> => {
    const deviceParam = device ? `&device=${encodeURIComponent(device)}` : '';
    const response = await axios.get(
        `${BACKEND_URL}/retrieval/parse-query?text=${encodeURIComponent(text)}${deviceParam}`
    );
    return response.data as Partial<SearchQuery>;
};

export type LocationSummaryItem = {
    id?: string;
    name: string;
    address?: string;
    country: string;
    info?: string;
    latitude?: number;
    longitude?: number;
    count: number;
};
export type CountItem = { name: string; count: number };
export type SearchResult = {
    segments: ImageObject[][];
    topLocations: LocationSummaryItem[];
    topCountries: CountItem[];
    topPeople: CountItem[];
};

export const searchImages = async (
    device: string,
    query: SearchQuery,
    sortBy: 'time' | 'relevance' = 'time',
    options?: { imagePaths?: string[]; imageBlobs?: Blob[] }
): Promise<SearchResult> => {
    const { weekCells, monthCells, ...rest } = query;
    const queryJson = JSON.stringify({
        ...rest,
        timeDayCells: weekCells,
        timeMonthCells: monthCells,
    });

    const formData = new FormData();
    formData.append('query', queryJson);
    options?.imagePaths?.forEach((p) => formData.append('image_paths', p));
    options?.imageBlobs?.forEach((b, i) => formData.append('files', b, `query_image_${i}`));

    const response = await axios.post(
        `${BACKEND_URL}/retrieval/search-images?device=${encodeURIComponent(device)}&sort_by=${sortBy}`,
        formData,
    );
    return response.data as SearchResult;
};

export const similarImages = async (device: string, imagePath: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/retrieval/similar-images?image=${encodeURIComponent(imagePath)}&device=${encodeURIComponent(device)}`
    );
    return response.data as ImageObject[];
};

export const similarImagesPost = async (device: string, blobUrl: string) => {
    const formData = new FormData();
    const blobResponse = await fetch(blobUrl);
    const blob = await blobResponse.blob();
    formData.append('file', blob, 'query_image');

    const response = await axios.post(
        `${BACKEND_URL}/retrieval/similar-images?device=${encodeURIComponent(device)}`,
        formData,
        {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        }
    );
    return response.data as ImageObject[];
};

export const deleteImage = async (device: string, imagePath: string) => {
    const response = await axios.delete(
        `${BACKEND_URL}/delete/delete-image?device=${encodeURIComponent(device)}`,
        {
            data: { imagePath },
        }
    );
    return response.data;
};

export const deleteImages = async (device: string, imagePaths: string[]) => {
    const response = await axios.delete(
        `${BACKEND_URL}/delete/delete-images?device=${encodeURIComponent(device)}`,
        {
            data: { imagePaths },
        }
    );
    return response.data;
};

export const getDeletedImages = async (device: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/delete/get-deleted-images?device=${encodeURIComponent(device)}`
    );
    return response.data as ImageObject[];
};

export const restoreImage = async (device: string, imagePath: string) => {
    const response = await axios.post(
        `${BACKEND_URL}/delete/restore-image?device=${encodeURIComponent(device)}`,
        {
            imagePath,
        }
    );
    return response.data;
};

export const forceDeleteImage = async (device: string, imagePath: string) => {
    const response = await axios.delete(
        `${BACKEND_URL}/delete/force-delete-image?device=${encodeURIComponent(device)}`,
        {
            data: { imagePath },
        }
    );
    return response.data;
};

export const forceDeleteImages = async (
    device: string,
    imagePaths: string[]
) => {
    const response = await axios.delete(
        `${BACKEND_URL}/delete/force-delete-images?device=${encodeURIComponent(device)}`,
        {
            data: { imagePaths },
        }
    );
    return response.data;
};

export const getUserGoals = async (device: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/get-targets?device=${encodeURIComponent(device)}`
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
    device: string
) => {
    const response = await axios.post(
        `${BACKEND_URL}/update-targets?device=${encodeURIComponent(device)}`,
        goals.map((goal) => [goal.name, goal.type, goal.query_prompt || ''])
    );
    return response.data;
};

export const getFaces = async (device: string, blobUrls: string[]) => {
    const formData = new FormData();
    for (let i = 0; i < blobUrls.length; i++) {
        const blobResponse = await fetch(blobUrls[i]);
        const blob = await blobResponse.blob();
        formData.append('files', blob, `face_image_${i}`);
    }
    const response = await axios.post(
        `${BACKEND_URL}/face/get-faces?device=${encodeURIComponent(device)}`,
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
    device: string,
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
        `${BACKEND_URL}/face/add-to-whitelist?device=${encodeURIComponent(device)}&name=${name}`,
        formData,
        {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        }
    );
    return response.data;
};

export const getWhiteList = async (device: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/face/get-whitelist?device=${encodeURIComponent(device)}`
    );
    return response.data as { name: string; images: string[] }[];
};

export const removeFromWhiteList = async (device: string, name: string) => {
    const response = await axios.delete(
        `${BACKEND_URL}/face/remove-from-whitelist?device=${encodeURIComponent(device)}&name=${name}`
    );
    return response.data;
};

export const getImagesByPerson = async (device: string, name: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/face/images-by-name?device=${encodeURIComponent(device)}&name=${encodeURIComponent(name)}`
    );
    return response.data as { imagePath: string; thumbnail: string; timestamp: string }[];
};

export const relabelRecentFaces = async (device: string, hours = 24) => {
    const response = await axios.post(
        `${BACKEND_URL}/face/relabel-recent?device=${encodeURIComponent(device)}&hours=${hours}`
    );
    return response.data as { queued: number; hours: number };
};

export const getRecognitionMode = async (device: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/face/recognition-mode?device=${encodeURIComponent(device)}`
    );
    return response.data as { keepFaceRecognition: boolean };
};

export const setRecognitionMode = async (device: string, keep: boolean) => {
    const response = await axios.put(
        `${BACKEND_URL}/face/set-recognition-mode?device=${encodeURIComponent(device)}&keep=${keep}`,
        {
            headers: {
                'Content-Type': 'application/json',
            },
        }
    );
    return response.data as { keepFaceRecognition: boolean; changed: boolean };
};

export const getAllDeviceSettings = async () => {
    const response = await axios.get(`${BACKEND_URL}/face/all-device-settings`);
    return response.data as { deviceId: string; keepFaceRecognition: boolean }[];
};

export const uploadAndSegment = async (blobUrl: string, points: Point[]) => {
    const formData = new FormData();
    const blobResponse = await fetch(blobUrl);
    const blob = await blobResponse.blob();
    formData.append('file', blob, 'segment_image');
    formData.append('points', JSON.stringify(points.map((p) => [p.x, p.y])));

    try {
        const response = await axios.post(
            `${BACKEND_URL}/annotations/segment-image`,
            formData,
            {
                headers: { 'Content-Type': 'multipart/form-data' },
            }
        );
        return response.data as {
            visualisation: string;
            masks: string[];
            bboxes: [number, number, number, number][];
        };
    } catch (error) {
        console.error('Segmentation failed', error);
        return {
            visualisation: '',
            masks: [],
            bboxes: [],
        };
    }
};

export const addAnnotation = async (
    device: string,
    imagePath: string,
    points: Point[],
    author: string,
    label?: string
) => {
    const response = await axios.post(
        `${BACKEND_URL}/annotations/add-annotation?device=${encodeURIComponent(device)}`,
        {
            imagePath,
            points: points.map((p) => [Math.round(p.x), Math.round(p.y)]),
            author,
            label,
        }
    );
    return response.data;
};

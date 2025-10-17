import axios from 'axios';
import { BACKEND_URL } from '../constants/urls';
import { ImageObject } from '@utils/types'

export const getImages = async (page: number = 1, date?: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/get-images?page=${page}${date ? `&date=${date}` : ''}`
    );
    return response.data as {
        date: string;
        images: ImageObject[];
        total_pages: number;
    };
};


export const getImagesByHour = async (date: string, hour: number, page: number = 1) => {
    const response = await axios.get(
        `${BACKEND_URL}/get-images-by-hour?date=${date}&hour=${hour}&page=${page}`
    );
    return response.data as {
        date: string;
        hour: number;
        images: ImageObject[];
        segments: ImageObject[][];
        available_hours: number[];
        total_pages: number;
    };
}


export const getAllDates = async () => {
    const response = await axios.get(`${BACKEND_URL}/get-all-dates`);
    console.log('response', response.data);
    return response.data as string[];
};

export const searchImages = async (query: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/search-images?query=${query}`
    );
    return response.data as ImageObject[];
};

export const similarImages = async (imagePath: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/similar-images?image=${encodeURIComponent(imagePath)}`
    );
    return response.data as ImageObject[];
}

export const deleteImage = async (imagePath: string) => {
    const response = await axios.delete(`${BACKEND_URL}/delete-image`, {
        data: { imagePath }
    });
    return response.data;
};

export const getDeletedImages = async () => {
    const response = await axios.get(`${BACKEND_URL}/get-deleted-images`);
    return response.data as ImageObject[];
};

export const restoreImage = async (imagePath: string) => {
    const response = await axios.post(`${BACKEND_URL}/restore-image`, {
        imagePath
    });
    return response.data;
};

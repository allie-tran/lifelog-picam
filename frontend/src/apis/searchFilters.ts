import { LocationData } from '@utils/types';
import axios from 'apis/defaultAxios';

export const getAvailableValues = async (
    device: string,
    filterName: string,
    extraParams: Record<string, any> = {}
): Promise<string[]> => {
    const response = await axios.post(
        `/explore/available-values?device=${device}`,
        {
            field: filterName,
            extraParams,
        }
    );

    return response.data as string[];
};

export const getLocations = async (
    device: string,
    countries: string[]
): Promise<LocationData[]> => {
    const response = await axios.post(
        `/explore/get-locations?device=${device}`,
        {
            field: 'location',
            extraParams: { country: countries },
        }
    );
    return response.data as LocationData[];
};

export const getMovingPeriods = async (
    device: string,
    countries: string[]
): Promise<LocationData[]> => {
    const response = await axios.post(
        `/explore/get-moving-periods?device=${device}`,
        {
            field: 'location',
            extraParams: { country: countries },
        }
    );
    return response.data as LocationData[];
};

export const searchLocations = async (
    device: string,
    q: string,
    limit = 20
): Promise<LocationData[]> => {
    const response = await axios.get(
        `/explore/search-locations`,
        { params: { device, q, limit } }
    );
    return response.data as LocationData[];
};

export const getAllFaces = async (device: string) => {
    const response = await axios.get(
        `/explore/all-faces?device=${encodeURIComponent(device)}`
    );
    return response.data as { name: string; images: string[]; id: string }[];
};

export const getMapMarkers = async (device: string, countries: string[]) => {
    const response = await axios.post(
        `/explore/locations/map-markers?device=${device}`,
        {
            field: 'location',
            extraParams: { country: countries },
        }
    );
    return response.data as {
        id: string;
        lat: number;
        lng: number;
        name: string;
        weight: number;
    }[];
};

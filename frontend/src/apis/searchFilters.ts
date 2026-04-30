import { LocationData } from '@utils/types';
import axios from 'apis/defaultAxios';

export const getAvailableValues = async (
    deviceId: string,
    filterName: string,
    extraParams: Record<string, any> = {}
): Promise<string[]> => {
    const response = await axios.post(
        `/explore/available-values?device=${deviceId}`,
        {
            field: filterName,
            extraParams,
        }
    );

    return response.data as string[];
};

export const getLocations = async (
    deviceId: string,
    countries: string[]
): Promise<LocationData[]> => {
    const response = await axios.post(
        `/explore/get-locations?device=${deviceId}`,
        {
            field: 'location',
            extraParams: { country: countries },
        }
    );
    return response.data as LocationData[];
};

export const getMovingPeriods = async (
    deviceId: string,
    countries: string[]
): Promise<LocationData[]> => {
    const response = await axios.post(
        `/explore/get-moving-periods?device=${deviceId}`,
        {
            field: 'location',
            extraParams: { country: countries },
        }
    );
    return response.data as LocationData[];
};

export const getAllFaces = async (deviceId: string) => {
    const response = await axios.get(
        `/explore/all-faces?device=${encodeURIComponent(deviceId)}`
    );
    return response.data as { name: string; images: string[], id: string }[];
};

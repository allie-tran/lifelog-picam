import { LocationData } from '@utils/types';
import axios from 'apis/defaultAxios';

export const getAvailableValues = async (
    deviceId: string,
    filterName: string,
    extraParams: Record<string, any> = {}
): Promise<string[]> => {
    try {
        const response = await axios.post(
            `/explore/available-values?device=${deviceId}`,
            {
                field: filterName,
                extraParams,
            }
        );

        return response.data as string[];
    } catch (error) {
        console.error(`Error fetching values for filter ${filterName}:`, error);
        throw error;
    }
};

export const getLocations = async (
    deviceId: string,
    countries: string[]
): Promise<LocationData[]> => {
    try {
        const response = await axios.post(
            `/explore/get-locations?device=${deviceId}`,
            {
                field: 'location',
                extraParams: { country: countries },
            }
        );
        return response.data as LocationData[];
    } catch (error) {
        console.error('Error fetching locations:', error);
        throw error;
    }
}

export const getAllFaces = async (deviceId: string) => {
    const response = await axios.get(
        `/explore/all-faces?device=${encodeURIComponent(deviceId)}`
    );
    return response.data as { name: string; images: string[] }[];
}

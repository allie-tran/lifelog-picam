import { DaySummary } from '@utils/types';
import axios from 'axios';
import { BACKEND_URL } from '../constants/urls';

export const processDate = async (deviceId: string, dateString: string, reset: boolean = false) => {
    const response = await axios.get(
        `${BACKEND_URL}/process-date?date=${encodeURIComponent(dateString)}&device=${encodeURIComponent(deviceId)}&reset=${reset}`
    );
    return response.data;
}

export const changeSegmentActivity = async (deviceId: string, segmentId: number, newActivityInfo: string) => {
    const response = await axios.post(
        `${BACKEND_URL}/change-segment-activity?device=${encodeURIComponent(deviceId)}`,
        {
            segmentId,
            newActivityInfo,
        }
    );
    return response.data
}

export const getDaySummary = async (deviceId: string, dateString: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/day-summary?date=${encodeURIComponent(dateString)}&device=${encodeURIComponent(deviceId)}`
    );
    return response.data as DaySummary;
}

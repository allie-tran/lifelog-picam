import { DaySummary, GPSData } from '@utils/types';
import axios from 'axios';
import { BACKEND_URL } from '../constants/urls';

export const processDate = async (deviceId: string, dateString: string, resegment: boolean, reannotate: boolean) => {
    const response = await axios.get(
        `${BACKEND_URL}/process-date?date=${encodeURIComponent(dateString)}&device=${encodeURIComponent(deviceId)}&resegment=${resegment}&reannotate=${reannotate}`
    );
    return response.data;
}

export const changeSegmentActivity = async (deviceId: string, date: string, segmentId: number, newActivityInfo: string) => {
    const response = await axios.post(
        `${BACKEND_URL}/change-segment-activity?device=${encodeURIComponent(deviceId)}`,
        {
            date,
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


export const getGPSByDate = async (deviceId: string, dateString: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/location/get-gps-by-date?date=${encodeURIComponent(dateString)}&device=${encodeURIComponent(deviceId)}`
    );
    return response.data as GPSData[];
}

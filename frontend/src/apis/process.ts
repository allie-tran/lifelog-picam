import { CurrentStatus, DaySummary, GPSData } from '@utils/types';
import axios from 'axios';
import { BACKEND_URL } from '../constants/urls';

export const processDate = async (device: string, dateString: string, resegment: boolean, reannotate: boolean) => {
    const response = await axios.get(
        `${BACKEND_URL}/process-date?date=${encodeURIComponent(dateString)}&device=${encodeURIComponent(device)}&resegment=${resegment}&reannotate=${reannotate}`
    );
    return response.data;
}

export const changeSegmentActivity = async (device: string, date: string, segmentId: number, newActivityInfo: string) => {
    const response = await axios.post(
        `${BACKEND_URL}/change-segment-activity?device=${encodeURIComponent(device)}`,
        {
            date,
            segmentId,
            newActivityInfo,
        }
    );
    return response.data
}

export const getDaySummary = async (device: string, dateString: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/day-summary?date=${encodeURIComponent(dateString)}&device=${encodeURIComponent(device)}`
    );
    return response.data as DaySummary;
}


export type GpsTrackData = { rawGps: GPSData[]; imageGps: GPSData[] };

export const getGPSByDate = async (device: string, dateString: string): Promise<GpsTrackData> => {
    const response = await axios.get(
        `${BACKEND_URL}/location/get-gps-by-date?date=${encodeURIComponent(dateString)}&device=${encodeURIComponent(device)}`
    );
    return response.data as GpsTrackData;
}

export const getCurrentStatus = async (device: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/status/current?device=${encodeURIComponent(device)}`
    );
    return response.data as CurrentStatus;
}

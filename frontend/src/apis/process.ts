import { CurrentStatus, DaySummary, GPSData, PeriodSummary } from '@utils/types';
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


export const getPeriodSummary = async (
    device: string,
    kind: 'week' | 'month' | 'trip' | 'custom',
    start: string,
    end: string
): Promise<PeriodSummary | null> => {
    const response = await axios.get(
        `${BACKEND_URL}/period-summary?device=${encodeURIComponent(device)}` +
        `&kind=${kind}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`
    );
    return response.data as PeriodSummary | null;
};


export type TripSpan = { start: string; end: string; days: number; label: string };

export const getTrips = async (device: string, windowDays?: number): Promise<TripSpan[]> => {
    // No windowDays → detect over the device's full history (all past trips).
    const win = windowDays != null ? `&window_days=${windowDays}` : '';
    const response = await axios.get(
        `${BACKEND_URL}/trips?device=${encodeURIComponent(device)}${win}`
    );
    return response.data as TripSpan[];
};


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

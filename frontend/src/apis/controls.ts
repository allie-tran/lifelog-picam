import { BACKEND_URL } from '../constants/urls';
import axios from 'apis/defaultAxios';

export const getSettingsRequest = async () => {
    const response = await axios.get(`${BACKEND_URL}/controls/settings`);
    return response.data as {
        captureMode: string;
        videoSettings: {
            fps: number;
            maxDuration: number;
        };
        timelapseSettings: {
            interval: number;
        };
    };
};

export const toogleModeRequest = async (mode: 'photo' | 'video') => {
    const response = await axios.post(
        `${BACKEND_URL}/controls/toggle_mode?mode=${mode}`
    );
    return response.data;
};

export const sendGPS = async (
    latitude: number,
    longitude: number,
    elevation: number,
    deviceId: string,
    time: string
) => {
    const response = await axios.put(
        `${BACKEND_URL}/location/upload-gps`,
        {
            latitude,
            longitude,
            elevation,
            timestamp: time,
            deviceId,
        },
    );

    return response.data;
};

export const processGPS = async (deviceId: string, date: string, deviceSecureId: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/location/process-gps?device=${deviceId}&date=${date}`,
        {
            headers: {
                'X-Device-ID': deviceSecureId,
            },
        }
    );
    return response.data;
}

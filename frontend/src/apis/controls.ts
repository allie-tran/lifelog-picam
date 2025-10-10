import axios from 'axios';
import { BACKEND_URL } from '../constants/urls';

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
    }
}

export const toogleModeRequest = async (mode: 'photo' | 'video') => {
    const response = await axios.post(`${BACKEND_URL}/controls/toggle_mode?mode=${mode}`);
    return response.data;
}

import axios from 'axios';
import { BACKEND_URL } from '../constants/urls';
import { SummarySegment } from '@utils/types';

export const processDate = async (dateString: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/process-date?date=${encodeURIComponent(dateString)}`
    );
    return response.data;
}

export const getDaySummary = async (dateString: string) => {
    const response = await axios.get(
        `${BACKEND_URL}/day-summary?date=${encodeURIComponent(dateString)}`
    );
    return response.data as {
        date: string;
        segments: SummarySegment[];
        summaryText: string;
    };
}

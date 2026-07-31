import axios from 'apis/defaultAxios';
import { BACKEND_URL } from '../constants/urls';

export type StopVenueCandidate = {
    name: string;
    category?: string | null;
    osmType?: string | null;
    osmId?: string | null;
    latitude?: number | null;
    longitude?: number | null;
    distanceM?: number | null;
    isCurrent?: boolean;
};

// Nearby venue options (offline OSM gazetteer) for manually correcting the
// reverse-geocode of a stop, without the LLM. `segmentIds` are the clicked
// DayNav run's segment ids.
export const getStopCandidates = async (
    device: string,
    date: string,
    segmentIds: number[]
): Promise<StopVenueCandidate[]> => {
    const response = await axios.get(`${BACKEND_URL}/location/stop-candidates`, {
        params: { device, date, segmentIds: segmentIds.join(',') },
    });
    return response.data as StopVenueCandidate[];
};

// Set the stop's venue. Reassigns ONLY the given segments (not revisits/neighbours).
export const correctStop = async (args: {
    device: string;
    date: string;
    segmentIds: number[];
    name: string;
    osmType?: string | null;
    osmId?: string | null;
}): Promise<{ success: boolean; message: string }> => {
    const response = await axios.post(`${BACKEND_URL}/location/correct-stop`, {
        device: args.device,
        date: args.date,
        segmentIds: args.segmentIds,
        name: args.name,
        osmType: args.osmType ?? null,
        osmId: args.osmId ?? null,
    });
    return response.data;
};

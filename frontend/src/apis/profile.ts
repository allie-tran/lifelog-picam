import axios from 'apis/defaultAxios';
import { BACKEND_URL } from '../constants/urls';

export type LabelKind = 'home' | 'work' | 'other';

export interface LabeledLocation {
    locationId: string;
    label: string;
    labelKind: LabelKind;
    name?: string | null;
    latitude?: number | null;
    longitude?: number | null;
    address?: string | null;
}

export interface LabelRequest {
    locationId?: string | null;   // existing detected stop; omit for a manual pin
    label: string;
    labelKind: LabelKind;
    name?: string | null;         // required for a manual pin
    latitude?: number | null;     // required for a manual pin
    longitude?: number | null;
}

export interface StopOption {
    locationId: string;
    name: string;
    address?: string | null;
    latitude: number;
    longitude: number;
    count: number;
    label?: string | null;
    labelKind?: LabelKind | null;
}

export interface SensorStatus {
    deviceId: string;
    deviceNickname?: string | null;
    sensorType: string;
    lastSeen?: string | null;
}

// ── Labeled locations (per-user) ────────────────────────────────────────────

export const getLabeledLocations = async (): Promise<LabeledLocation[]> => {
    const response = await axios.get(`${BACKEND_URL}/location/labeled`);
    return response.data as LabeledLocation[];
};

export const putLabel = async (req: LabelRequest): Promise<{ locationId: string }> => {
    const response = await axios.put(`${BACKEND_URL}/location/label`, req);
    return response.data;
};

export const deleteLabel = async (locationId: string): Promise<void> => {
    await axios.delete(`${BACKEND_URL}/location/label`, {
        params: { location_id: locationId },
    });
};

export const getStops = async (device: string): Promise<StopOption[]> => {
    const response = await axios.get(
        `${BACKEND_URL}/location/stops?device=${encodeURIComponent(device)}`
    );
    return response.data as StopOption[];
};

// ── Sensor devices ──────────────────────────────────────────────────────────

export const getMySensors = async (): Promise<SensorStatus[]> => {
    const response = await axios.get(`${BACKEND_URL}/auth/my-sensors`);
    return response.data as SensorStatus[];
};

export const renameSensor = async (
    deviceId: string,
    sensorType: string,
    nickname: string
): Promise<void> => {
    await axios.put(`${BACKEND_URL}/auth/rename-sensor`, null, {
        params: { device_id: deviceId, sensor_type: sensorType, nickname },
    });
};

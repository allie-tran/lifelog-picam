import { DayOfWeek, Month, Season, TimeOfDay } from "types/filters";

declare module '@mui/material/styles' {
    interface Theme {
        status: {
            danger: string;
        };
    }
    // allow configuration using `createTheme()`
    interface ThemeOptions {
        status?: {
            danger?: string;
        };
    }
}

export type GPSData = {
    latitude: number;
    longitude: number;
    timestamp: number;
    elevation: number;
};

export type LocationData = {
    id?: string;
    name?: string;
    stop?: boolean;
    // admin hierarchy
    suburb?: string;
    city?: string;
    region?: string;
    country?: string;
    postcode?: string;
    // geocoder output
    address?: string;
    timezone?: string;
    latitude?: number;
    longitude?: number;
    // enrichment
    wikidataId?: string;
    description?: string;
    categories?: string;
    // legacy
    info?: string;
};

type ImageObject = {
    imagePath: string;
    thumbnail: string;
    timestamp: string;
    timezone: string;
    isVideo: boolean;
    activity?: string;
    activityConfidence?: number;
    activityDescription?: string;
    segmentId?: string;
    new?: boolean;
};

export type ObjectDetection = {
    label: string;
    confidence: number;
    bbox: [number, number, number, number]; // [x_min, y_min, x_max, y_max]
};

export type PersonDetection = ObjectDetection & {
    clusterId?: string | null;
    clusterName?: string | null;
};

export type ImageWithMetadata = {
    imagePath: string;
    timestamp: string;
    timezone: string;
    gps?: GPSData | null;
    location?: LocationData | null;
    objects: ObjectDetection[];
    people: PersonDetection[];
};


export type ResultSegment = {
    images: ImageObject[];
    location: LocationData;
    gps: GPSData[];
}

type SummarySegment = {
    representativeImage: ImageObject;
    representativeImages: ImageObject[];
    segmentIndex: number;
    activity: string;
    startTime: string;
    endTime: string;
    duration: number;
};

// Define the enum to match your backend ActionType
export enum ActionType {
    BURST = 'burst',
    PERIOD = 'period',
    BINARY = 'binary',
}

export interface CustomGoal {
    name: string;
    type: ActionType;
    query_prompt?: string; // Optional field for additional details
}

type DaySummary = {
    date: string;
    segments: SummarySegment[];
    summaryText: string;
    updated: boolean;
    device: string;

    // 1. Binary: e.g., {"Social": 120.5, "Focus": 45.0}
    binaryMetrics: Record<string, number>;

    // 2. Periods: e.g., {"Eating": [segment1, segment2]}
    periodMetrics: Record<string, SummarySegment[]>;

    // 3. Bursts: e.g., {"Drinking Water": [1715200000, 1715200500]}
    burstMetrics: Record<string, number[]>;

    // Summaries: e.g., {"Eating": "Healthy lunch at desk"}
    customSummaries: Record<string, string>;

    categoryMinutes: Record<string, number>;
    totalImages: number;
    totalMinutes: number;
};

interface Point {
    x: number;
    y: number;
}

export type { ImageObject, SummarySegment, DaySummary, Point };

export type SearchQuery = {
    text: string;
    isImageQuery: boolean;

    // temporal
    timeOfDays: TimeOfDay[];
    dayOfWeeks: DayOfWeek[];
    seasons: Season[];
    months: Month[];
    years: number[];
    customRanges: { start: string; end: string }[];

    // location
    isMoving: boolean,
    countries: string[];
    locationIds: string[];
    bounds: [number, number, number, number] | null;

    // people
    peopleIds: string[];
}

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
    count?: number;
};

type ImageObject = {
    imagePath: string;
    thumbnail: string;
    gridThumbnail?: string; // small derivative for grid; falls back to thumbnail
    timestamp: string;
    timezone: string;
    isVideo: boolean;
    activity?: string;
    activityGroup?: string;
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
    segmentId?: number;
    images: ImageObject[];
    location: LocationData;
    gps: GPSData[];
}

type SummarySegment = {
    segmentId?: number | null;
    segmentIndex: number;
    representativeImage: ImageObject;
    representativeImages: ImageObject[];
    activity: string;
    activityGroup: string;
    startTime: string;
    endTime: string;
    timezone?: string | null;
    duration: number;
    locationName?: string | null;
    locationStop?: boolean | null;
    locationLatitude?: number | null;
    locationLongitude?: number | null;
};

type LocationVisit = {
    visitIndex: number;
    locationName?: string | null;
    locationStop?: boolean | null;
    locationLatitude?: number | null;
    locationLongitude?: number | null;
    startTime: string;
    endTime: string;
    timezone?: string | null;
    duration: number;
    segmentIds: number[];
    segmentIndices: number[];
    activityGroups: string[];
    description: string;
    eventContext?: string | null;
    representativeImage?: ImageObject | null;
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
    locationVisits?: LocationVisit[];
    summaryText: string;
    updated: boolean;
    device: string;
    processing?: boolean;

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

// ── Multi-day period summaries (week / month / trip / custom) ──────────────
export type TopLocation = {
    name: string;
    latitude?: number | null;
    longitude?: number | null;
    days: number;
    visits: number;
    minutes: number;
    representativeImage?: ImageObject | null;
};

export type BioTrendPoint = {
    date: string;
    sleepMinutes?: number | null;
    avgHr?: number | null;
    stepCount?: number | null;
};

export type BioTrend = {
    avgSleepMinutes?: number | null;
    avgHr?: number | null;
    restingHr?: number | null;
    maxHr?: number | null;
    avgSteps?: number | null;
    series: BioTrendPoint[];
};

export type TrendItem = {
    metric: string;
    current?: number | null;
    previous?: number | null;
    delta?: number | null;
    direction: string; // "up" | "down" | "flat" | "new" | "gone"
    note: string;
};

export type PeriodSummary = {
    kind: string; // "week" | "month" | "trip" | "custom"
    device: string;
    startDate: string;
    endDate: string;
    label: string;
    dayDates: string[];
    activeDays: number;
    childKind: string;
    childKeys: string[];
    categoryMinutes: Record<string, number>;
    totalMinutes: number;
    totalImages: number;
    binaryTotals: Record<string, number>;
    burstTotals: Record<string, number>;
    topLocations: TopLocation[];
    bioTrend?: BioTrend | null;
    summaryText: string;
    highlights: string[];
    trends: TrendItem[];
    updated: boolean;
    processing: boolean;
    generatedAt?: string | null;
    sourceSig?: string | null;
};

export type { ImageObject, SummarySegment, LocationVisit, DaySummary, Point };

export type SensorStatus = {
    deviceId: string;
    sensorType: string;
    nickname?: string;
    lastSeen?: string;
    online: boolean;
};

export type CurrentStatus = {
    cameraLastSeen?: string;
    cameraOnline: boolean;
    currentActivity?: string;
    currentActivityDescription?: string;
    currentLocation?: LocationData;
    currentThumbnail?: string;
    segmentSince?: string;
    locationSince?: string;
    currentLat?: number;
    currentLon?: number;
    sensors: SensorStatus[];
    summary?: string;
    summaryUpdatedAt?: string;
};

export interface Notification {
    id: string;
    device: string;
    date: string;
    timestamp?: string;
    read: boolean;
    type: 'new_location' | 'unusual_activity' | 'day_complete' | 'novelty' | string;
    title: string;
    body?: string;
    imagePath?: string;
    segmentId?: number;
}

// --- Chat assistant ---
export interface TokenUsage {
    prompt: number;
    completion: number;
    total: number;
}

export interface AppliedAction {
    tool: string;
    args: Record<string, any>;
    outcome: string;
}

export interface ChatMessage {
    role: 'user' | 'assistant' | 'tool';
    content: string;
    appliedActions?: AppliedAction[];
    tokenUsage?: TokenUsage;
    ts?: string;
}

export interface ChatThread {
    threadId: string;
    username?: string;
    device?: string;
    scope: 'day' | 'global' | string;
    date?: string | null;
    messages: ChatMessage[];
    tokenUsage: TokenUsage;
    created?: string;
    updated?: string;
}

export interface ChatTurnResponse {
    threadId: string;
    reply: string;
    appliedActions: AppliedAction[];
    messageUsage: TokenUsage;
    totalUsage: TokenUsage;
}

export interface ChatMemory {
    key: string;
    text: string;
    updated?: string;
}

export type SearchQuery = {
    text: string;
    isImageQuery: boolean;
    imageRef: string | null;

    // temporal
    timeOfDays: TimeOfDay[];
    dayOfWeeks: DayOfWeek[];
    seasons: Season[];
    months: Month[];
    years: number[];
    customRanges: { start: string; end: string }[];
    weekCells: { timeOfDay: TimeOfDay; dayOfWeek: DayOfWeek }[];
    monthCells: { dayOfWeek: DayOfWeek; month: Month }[];

    // location
    isMoving: boolean,
    countries: string[];
    locationIds: string[];
    bounds: [number, number, number, number] | null;

    // people
    peopleIds: string[];
}

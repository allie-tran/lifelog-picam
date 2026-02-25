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

type ImageObject = {
    imagePath: string;
    thumbnail: string;
    timestamp: number;
    isVideo: boolean;
    activity?: string;
    activityConfidence?: number;
    activityDescription?: string;
    segmentId?: string;
};

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

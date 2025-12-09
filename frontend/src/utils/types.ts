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

type DaySummary = {
    date: string;
    segments: SummarySegment[];
    summaryText: string;
    aloneMinutes: number;
    socialMinutes: number;
    categoryMinutes: { [key: string]: number };
    foodDrinkMinutes: number;
    foodDrinkSegments: SummarySegment[];
    foodDrinkSummary: string;
    totalImages: number;
    totalMinutes: number;
};

export type { ImageObject, SummarySegment, DaySummary };

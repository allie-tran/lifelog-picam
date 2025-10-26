declare module "@mui/material/styles" {
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
};

type SummarySegment = {
    segmentIndex: number;
    activity: string;
    startTime: string;
    endTime: string;
    duration: number;
}

export type { ImageObject, SummarySegment };

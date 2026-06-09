export interface ImageObject {
  imagePath: string;
  thumbnail?: string;
  timestamp: string;
  timezone?: string;
  isVideo: boolean;
  segmentId?: string;
  date?: string;
  hour?: number;
  description?: string;
  location?: string;
}

export interface SearchQuery {
  text: string;
  isImageQuery?: boolean;
  timeOfDays: string[];
  dayOfWeeks: string[];
  seasons: string[];
  months: string[];
  years: number[];
  customRanges: { start: string; end: string }[];
  isMoving: boolean;
  countries: string[];
  locationIds: string[];
  bounds: [number, number, number, number] | null;
  peopleIds: string[];
}

export interface LocationSummaryItem {
  id?: string;
  name: string;
  address?: string;
  country: string;
  info?: string;
  latitude?: number;
  longitude?: number;
  count: number;
}

export interface CountItem {
  name: string;
  count: number;
}

export interface BrowseSegment {
  images: ImageObject[];
  location?: { name?: string; address?: string; country?: string };
  gps?: { latitude: number; longitude: number }[];
}

export interface SearchResult {
  segments: ImageObject[][];
  topLocations: LocationSummaryItem[];
  topCountries: CountItem[];
  topPeople: CountItem[];
}

export interface SummarySegment {
  representativeImage: ImageObject;
  representativeImages: ImageObject[];
  segmentIndex: number;
  activity: string;
  startTime: string;
  endTime: string;
  duration: number;
}

export interface DaySummary {
  date: string;
  segments: SummarySegment[];
  summaryText: string;
  updated: boolean;
  device: string;
  binaryMetrics: Record<string, number>;
  periodMetrics: Record<string, SummarySegment[]>;
  burstMetrics: Record<string, number[]>;
  customSummaries: Record<string, string>;
  categoryMinutes: Record<string, number>;
  totalImages: number;
  totalMinutes: number;
}

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

export type RootStackParamList = {
  Login: undefined;
  Register: undefined;
  Main: undefined;
  Admin: undefined;
  Upload: undefined;
  DeletedImages: undefined;
  DeleteRange: undefined;
  LocationMap: { date?: string } | undefined;
};

export type MainTabParamList = {
  Browse: undefined;
  Search: undefined;
  People: undefined;
  GPS: undefined;
  Biometrics: undefined;
  DRES: undefined;
  Notifications: undefined;
  Settings: undefined;
};

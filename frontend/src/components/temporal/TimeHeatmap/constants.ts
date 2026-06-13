import { TimeOfDay } from 'types/filters';

export type ViewMode = 'weekday' | 'month' | 'calendar';

// Display order: chronological from morning to night
export const TOD_DISPLAY: { key: TimeOfDay; label: string; sub: string }[] = [
    { key: 'morning',   label: 'Morning',   sub: '05–11' },
    { key: 'midday',    label: 'Midday',    sub: '11–13' },
    { key: 'afternoon', label: 'Afternoon', sub: '13–17' },
    { key: 'evening',   label: 'Evening',   sub: '17–21' },
    { key: 'night',     label: 'Night',     sub: '21–05' },
];

export const DAY_ABBR = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
export const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export const hourToTodKey = (h: number): TimeOfDay => {
    if (h >= 5 && h < 11) return 'morning';
    if (h >= 11 && h < 13) return 'midday';
    if (h >= 13 && h < 17) return 'afternoon';
    if (h >= 17 && h < 21) return 'evening';
    return 'night';
};

export function toggle<T>(arr: T[], val: T): T[] {
    return arr.includes(val) ? arr.filter((x) => x !== val) : [...arr, val];
}

// GridView layout
export const ROW_LABEL_W = 88;
export const CELL_H = 24;

// CalendarView layout
export const CSIZ = 17;
export const CGAP = 2;

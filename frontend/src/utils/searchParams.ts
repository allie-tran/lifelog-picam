import { DayOfWeek, Month, Season, TimeOfDay } from 'types/filters';
import { SearchQuery } from '@utils/types';

const RANGE_SEP = '__';
const CELL_SEP = ':';

export const parseSearchParams = (sp: URLSearchParams): SearchQuery => ({
    text: sp.get('q') || '',
    isImageQuery: false,
    imageRef: null,
    timeOfDays: (sp.get('timeOfDays')?.split(',').filter(Boolean) ?? []) as TimeOfDay[],
    dayOfWeeks: (sp.get('dayOfWeeks')?.split(',').filter(Boolean) ?? []) as DayOfWeek[],
    seasons: (sp.get('seasons')?.split(',').filter(Boolean) ?? []) as Season[],
    months: (sp.get('months')?.split(',').filter(Boolean) ?? []) as Month[],
    years: sp.get('years')?.split(',').filter(Boolean).map(Number) ?? [],
    customRanges: sp
        .get('customRanges')
        ?.split(',')
        .filter(Boolean)
        .map((r) => {
            const [start, end] = r.split(RANGE_SEP);
            return { start, end: end ?? start };
        }) ?? [],
    weekCells: sp
        .get('weekCells')
        ?.split(',')
        .filter(Boolean)
        .map((c) => {
            const [timeOfDay, dayOfWeek] = c.split(CELL_SEP);
            return { timeOfDay: timeOfDay as TimeOfDay, dayOfWeek: dayOfWeek as DayOfWeek };
        }) ?? [],
    monthCells: sp
        .get('monthCells')
        ?.split(',')
        .filter(Boolean)
        .map((c) => {
            const [dayOfWeek, month] = c.split(CELL_SEP);
            return { dayOfWeek: dayOfWeek as DayOfWeek, month: month as Month };
        }) ?? [],
    isMoving: sp.get('isMoving') === 'true',
    countries: sp.get('countries')?.split(',').filter(Boolean) ?? [],
    locationIds: sp.get('locationIds')?.split(',').filter(Boolean) ?? [],
    bounds: (() => {
        const nums = sp.get('bounds')?.split(',').filter(Boolean).map(Number);
        return nums?.length === 4 ? (nums as [number, number, number, number]) : null;
    })(),
    peopleIds: sp.get('peopleIds')?.split(',').filter(Boolean) ?? [],
});

export const applyQueryToParams = (
    partial: Partial<SearchQuery>,
    base: URLSearchParams
): URLSearchParams => {
    const sp = new URLSearchParams(base);
    const set = (key: string, val: string | undefined | null) => {
        if (val) sp.set(key, val); else sp.delete(key);
    };
    if ('text' in partial) set('q', partial.text || null);
    if ('timeOfDays' in partial) set('timeOfDays', partial.timeOfDays?.join(','));
    if ('dayOfWeeks' in partial) set('dayOfWeeks', partial.dayOfWeeks?.join(','));
    if ('seasons' in partial) set('seasons', partial.seasons?.join(','));
    if ('months' in partial) set('months', partial.months?.join(','));
    if ('years' in partial) set('years', partial.years?.join(','));
    if ('customRanges' in partial)
        set('customRanges', partial.customRanges?.map((r) => `${r.start}${RANGE_SEP}${r.end}`).join(','));
    if ('weekCells' in partial)
        set('weekCells', partial.weekCells?.map((c) => `${c.timeOfDay}${CELL_SEP}${c.dayOfWeek}`).join(','));
    if ('monthCells' in partial)
        set('monthCells', partial.monthCells?.map((c) => `${c.dayOfWeek}${CELL_SEP}${c.month}`).join(','));
    if ('isMoving' in partial) { if (partial.isMoving) sp.set('isMoving', 'true'); else sp.delete('isMoving'); }
    if ('countries' in partial) set('countries', partial.countries?.join(','));
    if ('locationIds' in partial) {
        const newIds = partial.locationIds ?? [];
        set('locationIds', newIds.join(','));
        // Prune orphaned labels when IDs change
        if (sp.has('locationLabels')) {
            try {
                const labels: Record<string, string> = JSON.parse(sp.get('locationLabels')!);
                const pruned = Object.fromEntries(Object.entries(labels).filter(([k]) => newIds.includes(k)));
                if (Object.keys(pruned).length > 0) sp.set('locationLabels', JSON.stringify(pruned));
                else sp.delete('locationLabels');
            } catch { sp.delete('locationLabels'); }
        }
    }
    if ('bounds' in partial) set('bounds', partial.bounds?.join(','));
    if ('peopleIds' in partial) set('peopleIds', partial.peopleIds?.join(','));
    return sp;
};

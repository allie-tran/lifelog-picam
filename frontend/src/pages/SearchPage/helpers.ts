import { SearchQuery } from '@utils/types';

export const PAGE_SIZE = 20;

export const queryFilterChips = (entry: SearchQuery): string[] => {
    const chips: string[] = [];
    entry.timeOfDays?.forEach((t) => chips.push(t));
    entry.dayOfWeeks?.forEach((d) => chips.push(d.slice(0, 3)));
    entry.seasons?.forEach((s) => chips.push(s));
    entry.months?.forEach((m) => chips.push(m.slice(0, 3)));
    entry.years?.forEach((y) => chips.push(String(y)));
    if (entry.isMoving) chips.push('moving');
    entry.countries?.forEach((c) => chips.push(c));
    if ((entry.locationIds?.length ?? 0) > 0)
        chips.push(`${entry.locationIds!.length} place${entry.locationIds!.length > 1 ? 's' : ''}`);
    if ((entry.peopleIds?.length ?? 0) > 0)
        chips.push(`${entry.peopleIds!.length} person${entry.peopleIds!.length > 1 ? 's' : ''}`);
    return chips;
};

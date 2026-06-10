import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { SearchQuery } from '@utils/types';

interface SearchState {
    history: SearchQuery[];
}

const HISTORY_KEY = 'searchQueryHistory';

const loadHistory = (): SearchQuery[] => {
    try {
        const raw = localStorage.getItem(HISTORY_KEY);
        return raw ? (JSON.parse(raw) as SearchQuery[]) : [];
    } catch {
        return [];
    }
};

const saveHistory = (history: SearchQuery[]) => {
    try {
        localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
    } catch {}
};

const initialState: SearchState = {
    history: loadHistory(),
};

export const searchSlice = createSlice({
    name: 'search',
    initialState,
    reducers: {
        pushToHistory: (state, action: PayloadAction<SearchQuery>) => {
            const entry = action.payload;
            const hasContent =
                !!entry.text?.trim() ||
                (entry.timeOfDays?.length ?? 0) > 0 ||
                (entry.dayOfWeeks?.length ?? 0) > 0 ||
                (entry.months?.length ?? 0) > 0 ||
                (entry.years?.length ?? 0) > 0 ||
                (entry.seasons?.length ?? 0) > 0 ||
                (entry.countries?.length ?? 0) > 0 ||
                (entry.locationIds?.length ?? 0) > 0 ||
                (entry.peopleIds?.length ?? 0) > 0;
            if (!hasContent) return;
            const [latest] = state.history;
            if (latest && JSON.stringify(latest) === JSON.stringify(entry)) return;
            state.history = [entry, ...state.history].slice(0, 25);
            saveHistory(state.history);
        },
        removeFromHistory: (state, action: PayloadAction<number>) => {
            state.history = state.history.filter((_, i) => i !== action.payload);
            saveHistory(state.history);
        },
        clearHistory: (state) => {
            state.history = [];
            saveHistory([]);
        },
    },
});

export const { pushToHistory, removeFromHistory, clearHistory } = searchSlice.actions;
export default searchSlice.reducer;

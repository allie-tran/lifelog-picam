import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { SearchQuery } from '@utils/types';

interface SearchState {
    query: SearchQuery;
    history: SearchQuery[];
}

const EMPTY_QUERY: SearchQuery = {
    text: '',
    isImageQuery: false,
    timeOfDays: [],
    dayOfWeeks: [],
    seasons: [],
    months: [],
    years: [],
    customRanges: [],
    isMoving: false,
    countries: [],
    locationIds: [],
    bounds: null,
    peopleIds: [],
};

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
    query: EMPTY_QUERY,
    history: loadHistory(),
};

export const searchSlice = createSlice({
    name: 'search',
    initialState,
    reducers: {
        setSearchQuery: (state, action: PayloadAction<Partial<SearchQuery>>) => {
            state.query = { ...state.query, ...action.payload };
        },
        resetSearchQuery: (state) => {
            state.query = EMPTY_QUERY;
        },
        pushToHistory: (state, action: PayloadAction<SearchQuery>) => {
            const entry = action.payload;
            if (!entry.text?.trim()) return;
            // Drop duplicate of the most recent entry
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

export const {
    setSearchQuery,
    resetSearchQuery,
    pushToHistory,
    removeFromHistory,
    clearHistory,
} = searchSlice.actions;
export default searchSlice.reducer;


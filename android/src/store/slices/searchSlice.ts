import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { SearchQuery } from '../../types';

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

const loadHistory = (): SearchQuery[] => {
  // AsyncStorage is async; history is loaded at app start via a thunk
  return [];
};

interface SearchState {
  query: SearchQuery;
  history: SearchQuery[];
}

const searchSlice = createSlice({
  name: 'search',
  initialState: { query: EMPTY_QUERY, history: loadHistory() } as SearchState,
  reducers: {
    setSearchQuery(state, action: PayloadAction<Partial<SearchQuery>>) {
      state.query = { ...state.query, ...action.payload };
    },
    resetSearchQuery(state) {
      state.query = EMPTY_QUERY;
    },
    pushToHistory(state, action: PayloadAction<SearchQuery>) {
      const entry = action.payload;
      if (!entry.text?.trim()) return;
      const [latest] = state.history;
      if (latest && JSON.stringify(latest) === JSON.stringify(entry)) return;
      state.history = [entry, ...state.history].slice(0, 25);
    },
    removeFromHistory(state, action: PayloadAction<number>) {
      state.history = state.history.filter((_, i) => i !== action.payload);
    },
    clearHistory(state) {
      state.history = [];
    },
    setHistory(state, action: PayloadAction<SearchQuery[]>) {
      state.history = action.payload;
    },
  },
});

export const {
  setSearchQuery,
  resetSearchQuery,
  pushToHistory,
  removeFromHistory,
  clearHistory,
  setHistory,
} = searchSlice.actions;
export default searchSlice.reducer;

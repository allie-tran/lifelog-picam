import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { SearchQuery } from '@utils/types';

interface SearchState {
    query: SearchQuery;
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


const initialState: SearchState = {
    query: EMPTY_QUERY,
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
    },
});

export const { setSearchQuery, resetSearchQuery } = searchSlice.actions;
export default searchSlice.reducer;


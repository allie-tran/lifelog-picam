
import { Button, Stack, TextField } from '@mui/material';
import React from 'react';
import { useNavigate, useSearchParams } from 'react-router';

const SearchBar = () => {
    const [searchParams, _] = useSearchParams();
    const [query, setQuery] = React.useState(searchParams.get('query') || '');
    const navigate = useNavigate()

    const onSearch = (query: string) => {
        navigate('/search?query=' + encodeURIComponent(query))
    };

    return (
        <Stack direction="row" spacing={2} alignItems="center">
            <TextField
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search images..."
                sx={{ padding: '8px', width: '80dvw', marginRight: '8px' }}
                onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                        onSearch(query);
                    }
                }}
            />
            <Button
                variant="outlined"
                onClick={() => {
                    onSearch(query);
                }}
                sx={{ padding: '8px' }}
            >
                Search
            </Button>
        </Stack>
    );
};
export default SearchBar;

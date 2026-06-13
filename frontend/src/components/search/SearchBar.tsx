import { Button, Stack, TextField } from '@mui/material';
import React from 'react';
import { useNavigate, useSearchParams } from 'react-router';

const SearchBar = ({ visible = true }: { visible?: boolean }) => {
    const [searchParams, _] = useSearchParams();
    const [query, setQuery] = React.useState(searchParams.get('query') || '');
    const navigate = useNavigate();

    const onSearch = (query: string) => {
        navigate('/search?mode=text&&query=' + encodeURIComponent(query));
    };

    return (
        <Stack
            direction="row"
            spacing={2}
            alignItems="center"
            sx={{ display: visible ? 'flex' : 'none', width: '100%' }}
        >
            <TextField
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search images..."
                sx={{ padding: '8px', width: '100%', marginRight: '8px' }}
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
                sx={{ padding: 1.5, outline: '2px solid', minWidth: '100px' }}
            >
                <strong>Search</strong>
            </Button>
        </Stack>
    );
};
export default SearchBar;

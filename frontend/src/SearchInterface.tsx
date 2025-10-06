import { Button, Stack, TextField } from '@mui/material';
import React from 'react';
import './App.css';
import { searchImages } from './events';
import ModalWithCloseButton from './ModalWithCloseButton';
import { ImageObject } from './types';
import ImageWithDate from './ImageWithDate';
const SearchInterface = () => {
    const [query, setQuery] = React.useState('');
    const [results, setResults] = React.useState<ImageObject[]>([]);
    const [open, setOpen] = React.useState(false);
    const onSearch = (query: string) => {
        searchImages(query).then((data) => {
            setResults(data);
        });
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
                        setOpen(true);
                    }
                }}
            />
            <Button
                variant="outlined"
                onClick={() => {
                    onSearch(query);
                    setOpen(true);
                }}
                sx={{ padding: '8px' }}
            >
                Search
            </Button>
            <ModalWithCloseButton open={open} onClose={() => setOpen(false)}>
                {results.length === 0 && <div>No results found</div>}
                <Stack
                    spacing={2}
                    sx={{ width: '100%', flexWrap: 'wrap' }}
                    direction="row"
                    useFlexGap
                >
                    {results.map((image) => (
                        <ImageWithDate
                            key={image.image_path}
                            imagePath={image.image_path}
                            timestamp={image.timestamp}
                        />
                    ))}
                </Stack>
            </ModalWithCloseButton>
        </Stack>
    );
};
export default SearchInterface;

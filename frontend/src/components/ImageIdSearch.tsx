import { Button, Stack, TextField } from '@mui/material';
import React from 'react';
import { useNavigate, useSearchParams } from 'react-router';

const ImageIdSearch = ({ visible = true }: { visible?: boolean }) => {
    const [searchParams, _] = useSearchParams();
    const [imageId, setImageId] = React.useState(
        searchParams.get('image_id') || ''
    );
    const navigate = useNavigate();

    const onSearch = (query: string) => {
        navigate('/search?mode=id&&query=' + encodeURIComponent(query));
    };

    return (
        <Stack
            direction="row"
            spacing={2}
            alignItems="center"
            sx={{ display: visible ? 'flex' : 'none', width: '100%' }}
        >
            <TextField
                value={imageId}
                onChange={(e) => setImageId(e.target.value)}
                placeholder="Enter Image ID (e.g. 2016-04-12/20160412_123456.jpg)"
                sx={{ padding: '8px', width: '100%', marginRight: '8px' }}
                onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                        onSearch(imageId);
                    }
                }}
            />
            <Button
                variant="outlined"
                onClick={() => {
                    onSearch(imageId);
                }}
                sx={{ padding: 1.5, outline: '2px solid', minWidth: '100px' }}
            >
                <strong>Lookup</strong>
            </Button>
        </Stack>
    );
};
export default ImageIdSearch;

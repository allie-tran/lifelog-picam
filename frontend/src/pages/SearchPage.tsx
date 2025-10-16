import { searchImages } from 'apis/browsing';
import ImageWithDate from 'components/ImageWithDate';
import { Divider, Stack, Typography } from '@mui/material';
import { ImageObject } from '@utils/types';
import { useSearchParams } from 'react-router';
import useSWR from 'swr';
import SearchBar from 'components/SearchBar';

const SearchPage = () => {
    const [searchParams, _] = useSearchParams();

    const { data, isLoading } = useSWR(
        ['search', searchParams.get('query')],
        () => searchImages(searchParams.get('query') || ''),
        {
            revalidateOnFocus: false,
        }
    );
    const results: ImageObject[] = data || [];
    if (isLoading) {
        return <div>Loading...</div>;
    }

    return (
        <>
            <Typography variant="h4" align="center" marginTop={4} color="primary" fontWeight="bold">
                Search
            </Typography>
            <SearchBar />
            <Divider sx={{ marginY: 2 }} />
            <Typography variant="h6">
                Showing results for: "{searchParams.get('query')}"
            </Typography>
            <Stack spacing={2} alignItems="center">
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
            </Stack>
        </>
    );
};
export default SearchPage;

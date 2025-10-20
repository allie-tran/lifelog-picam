import { searchImages } from 'apis/browsing';
import ImageWithDate from 'components/ImageWithDate';
import { Divider, LinearProgress, Stack, Typography } from '@mui/material';
import { ImageObject } from '@utils/types';
import { useSearchParams } from 'react-router';
import useSWR from 'swr';
import SearchBar from 'components/SearchBar';
import { ImageZoom } from 'components/ImageZoom';
import { setZoomedImage } from 'reducers/zoomedImage';
import { useState } from 'react';
import { useAppDispatch } from 'reducers/hooks';

const SearchPage = () => {
    const dispatch = useAppDispatch();
    const [searchParams, _] = useSearchParams();
    const query = searchParams.get('query') || '';
    const { data, isLoading } = useSWR(
        ['search', query],
        () => searchImages(query),
        {
            revalidateOnFocus: false,
        }
    );
    const results: ImageObject[] = data || [];
    const [deleted, setDeleted] = useState<string[]>([]);

    if (isLoading) return <LinearProgress />;

    return (
        <>
            <Typography
                variant="h4"
                align="center"
                marginTop={4}
                color="primary"
                fontWeight="bold"
            >
                Search
            </Typography>
            <SearchBar />
            <Divider sx={{ marginY: 2 }} />
            {query && (
                <>
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
                            {results.map((image) =>
                                deleted.includes(image.imagePath) ? null : (
                                    <ImageWithDate
                                        image={image}
                                        onClick={() => {
                                            dispatch(
                                                setZoomedImage({
                                                    image: image.imagePath,
                                                    isVideo: image.isVideo,
                                                })
                                            );
                                        }}
                                        onDelete={() =>
                                            setDeleted([
                                                ...deleted,
                                                image.imagePath,
                                            ])
                                        }
                                    />
                                )
                            )}
                        </Stack>
                    </Stack>
                </>
            )}
            <ImageZoom
                onDelete={(imgPath?: string) => {
                    if (imgPath) {
                        setDeleted([...deleted, imgPath]);
                    }
                }}
            />
        </>
    );
};
export default SearchPage;

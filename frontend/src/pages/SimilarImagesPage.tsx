import { Divider, Stack, Typography } from '@mui/material';
import { ImageObject } from '@utils/types';
import { similarImages } from 'apis/browsing';
import ImageWithDate from 'components/ImageWithDate';
import { ImageZoom } from 'components/ImageZoom';
import dayjs from 'dayjs';
import { useState } from 'react';
import { useSearchParams } from 'react-router';
import { useAppDispatch } from 'reducers/hooks';
import { setZoomedImage } from 'reducers/zoomedImage';
import useSWR from 'swr';

const toTimestamp = (imagePath: string): number => {
    const str = imagePath.split('/').pop()?.split('.')[0] || '';
    const date = dayjs(str, 'YYYYMMDD_HHmmss');
    // to timestamp (number of milliseconds since epoch)
    return date.unix() * 1000;
};

const SimilarImages = () => {
    const [searchParams, _] = useSearchParams();
    const dispatch = useAppDispatch();

    const image: ImageObject = {
        imagePath: searchParams.get('image') || '',
        thumbnail: (searchParams.get('image') || '').split('.')[0] + '.webp',
        timestamp: toTimestamp(searchParams.get('image') || ''),
        isVideo: searchParams.get('image')?.endsWith('.mp4') || false,
    };

    const { data, isLoading } = useSWR(
        ['similar-images', searchParams.get('image')],
        () => similarImages(searchParams.get('image') || ''),
        {
            revalidateOnFocus: false,
        }
    );
    const [deleted, setDeleted] = useState<string[]>([]);
    const results: ImageObject[] = data || [];
    if (isLoading) {
        return <div>Loading...</div>;
    }

    return (
        <>
            <Typography
                variant="h4"
                align="center"
                color="primary"
                fontWeight="bold"
            >
                Similar Images
            </Typography>
            <Stack spacing={2} alignItems="center" marginTop={2}>
                <ImageWithDate
                    image={image}
                />
                <Divider flexItem />
                <Typography variant="h6">
                    Showing results for: "{searchParams.get('image')}"
                </Typography>
                {results.length === 0 && <div>No results found</div>}
                <Stack
                    spacing={2}
                    sx={{ flexWrap: 'wrap' }}
                    direction="row"
                    useFlexGap
                    justifyContent="center"
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
                                    setDeleted([...deleted, image.imagePath])
                                }
                            />
                        )
                    )}
                </Stack>
            </Stack>
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
export default SimilarImages;

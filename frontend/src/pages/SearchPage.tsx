import {
    Button,
    Divider,
    LinearProgress,
    Stack,
    Typography,
} from '@mui/material';
import { ImageObject } from '@utils/types';
import { deleteImage, searchImages } from 'apis/browsing';
import SearchBar from 'components/SearchBar';
import React, { useState } from 'react';
import { useSearchParams } from 'react-router';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import { setZoomedImage } from 'reducers/zoomedImage';
import useSWR from 'swr';
import '../App.css';
import ImageWithDate from '../components/ImageWithDate';
import { ImageZoom } from '../components/ImageZoom';
import DeviceSelect from './DeviceSelect';
import { CONFIDENCE_COLOURS } from 'constants/activityColors';
import { setLoading } from 'reducers/feedback';

const SearchPage = () => {
    const dispatch = useAppDispatch();
    const [searchParams, _] = useSearchParams();
    const query = searchParams.get('query') || '';
    const deviceId = useAppSelector((state) => state.auth.deviceId) || '';
    const { data, isLoading, mutate } = useSWR(
        ['search', query],
        () => searchImages(deviceId, query),
        {
            revalidateOnFocus: false,
        }
    );
    const results: ImageObject[][] = data || [];
    const [deleted, setDeleted] = useState<string[]>([]);

    const deleteRow = (imagePaths: string[]) => {
        dispatch(setLoading(true));
        Promise.all(imagePaths.map((path) => deleteImage(deviceId, path))).then(
            () => {
                mutate().then(() => dispatch(setLoading(false)));
            }
        );
    };

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
            <DeviceSelect />
            <SearchBar />
            <Divider sx={{ marginY: 2 }} />
            {query && (
                <>
                    <Typography variant="h6">
                        Showing results for: "{searchParams.get('query')}"
                    </Typography>
                    <Stack spacing={2} sx={{ width: '100%' }}>
                        {results.map((segment, index) => {
                            const firstImage = segment[0];

                            return (
                                <React.Fragment key={index}>
                                    <Typography
                                        variant="h6"
                                        fontWeight="bold"
                                        color={
                                            CONFIDENCE_COLOURS[
                                                firstImage.activityConfidence ||
                                                    'Low'
                                            ]
                                        }
                                    >
                                        {firstImage.activity
                                            ? `${firstImage.activity} (Confidence: ${firstImage.activityConfidence})`
                                            : 'No Activity Detected'}
                                    </Typography>
                                    <Typography>
                                        {firstImage.activityDescription}
                                    </Typography>
                                    <Stack
                                        direction="row"
                                        spacing={2}
                                        key={index}
                                        sx={{
                                            maxWidth: '100vw',
                                            overflowY: 'auto',
                                            height: '400px',
                                        }}
                                    >
                                        {segment.map((image: ImageObject) => (
                                            <ImageWithDate
                                                image={image}
                                                onClick={() => {
                                                    console.log(
                                                        'Setting zoomed image:',
                                                        image.imagePath
                                                    );
                                                    dispatch(
                                                        setZoomedImage({
                                                            image: image.imagePath,
                                                            isVideo:
                                                                image.isVideo,
                                                        })
                                                    );
                                                }}
                                                onDelete={() => mutate()}
                                            />
                                        ))}
                                    </Stack>
                                    <Button
                                        color="error"
                                        onClick={() => {
                                            const imagePaths = segment.map(
                                                (img) => img.imagePath
                                            );
                                            deleteRow(imagePaths);
                                        }}
                                    >
                                        Delete All {segment.length} Images in
                                        this Row
                                    </Button>
                                    <Divider flexItem />
                                </React.Fragment>
                            );
                        })}
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

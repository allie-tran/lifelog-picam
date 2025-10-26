import { ArchiveRounded, RestoreRounded } from '@mui/icons-material';
import { Button, IconButton, Stack } from '@mui/material';
import React from 'react';
import {
    forceDeleteImage,
    getDeletedImages,
    restoreImage,
} from '../apis/browsing';
import { ImageObject } from '@utils/types';
import ImageWithDate from './ImageWithDate';
import ModalWithCloseButton from './ModalWithCloseButton';
import { setLoading } from 'reducers/feedback';
import { useAppDispatch } from 'reducers/hooks';

const DeletedImages = () => {
    const dispatch = useAppDispatch();
    const [results, setResults] = React.useState<ImageObject[]>([]);
    const [open, setOpen] = React.useState(false);

    const fetchImages = () => {
        getDeletedImages().then((data) => {
            setResults(data);
            dispatch(setLoading(false));
        });
    };

    return (
        <Stack direction="row" spacing={2} alignItems="center">
            <IconButton
                size="large"
                color="secondary"
                onClick={() => {
                    fetchImages();
                    setOpen(true);
                }}
            >
                <ArchiveRounded />
            </IconButton>
            <ModalWithCloseButton open={open} onClose={() => setOpen(false)}>
                {results.length === 0 && <div>No results found</div>}
                <Stack
                    spacing={2}
                    sx={{ width: '100%', flexWrap: 'wrap' }}
                    direction="row"
                    useFlexGap
                    justifyContent="center"
                >
                    {results.map((image) => (
                        <ImageWithDate
                            image={image}
                            extra={
                                <Button
                                    color="error"
                                    size="small"
                                    sx={{ minWidth: 32 }}
                                    onClick={() => {
                                        dispatch(setLoading(true));
                                        restoreImage(image.imagePath).then(() =>
                                            fetchImages()
                                        );
                                    }}
                                >
                                    <RestoreRounded />
                                </Button>
                            }
                            onDelete={(image) => {
                                dispatch(setLoading(true));
                                forceDeleteImage(image).then(() =>
                                    fetchImages()
                                );
                            }}
                        />
                    ))}
                </Stack>
            </ModalWithCloseButton>
        </Stack>
    );
};
export default DeletedImages;

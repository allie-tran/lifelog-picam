import { ArchiveRounded, RestoreRounded } from '@mui/icons-material';
import { Button, CircularProgress, IconButton, Stack } from '@mui/material';
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
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import useSWR from 'swr';

const DeletedImages = () => {
    const dispatch = useAppDispatch();
    const [open, setOpen] = React.useState(false);
    const deviceId = useAppSelector((state) => state.auth.deviceId) || '';

    const { data, isLoading, mutate } = useSWR(
        ['deleted-images', deviceId],
        () => getDeletedImages(deviceId),
        {
            revalidateOnFocus: false,
        }
    );

    return (
        <Stack direction="row" spacing={2} alignItems="center">
            <IconButton
                size="large"
                color="secondary"
                onClick={() => {
                    setOpen(true);
                    mutate();
                }}
            >
                <ArchiveRounded />
            </IconButton>
            <ModalWithCloseButton open={open} onClose={() => setOpen(false)}>
                {isLoading ? <CircularProgress /> : null}
                {!isLoading && data && data.length === 0 && (
                    <div>No deleted images found</div>
                )}
                {!isLoading && data && data.length > 0 && (
                    <>
                        <Stack
                            direction="row"
                            justifyContent="center"
                            alignItems="center"
                        >
                            <Button
                                variant="outlined"
                                sx={{ mb: 2 }}
                                onClick={() => {
                                    data.forEach(
                                        (image: ImageObject, index: number) => {
                                            restoreImage(
                                                deviceId,
                                                image.imagePath
                                            ).then(() => {
                                                if (index === data.length - 1) {
                                                    mutate();
                                                }
                                            });
                                        }
                                    );
                                }}
                            >
                                Restore All
                            </Button>
                            <Button
                                variant="outlined"
                                color="error"
                                sx={{ mb: 2, ml: 2 }}
                                onClick={() => {
                                    data.forEach(
                                        (image: ImageObject, index: number) => {
                                            forceDeleteImage(
                                                deviceId,
                                                image.imagePath
                                            ).then(() => {
                                                if (index === data.length - 1) {
                                                    mutate();
                                                }
                                            });
                                        }
                                    );
                                }}
                            >
                                Delete All
                            </Button>
                        </Stack>
                        <Stack
                            spacing={2}
                            sx={{ width: '100%', flexWrap: 'wrap' }}
                            direction="row"
                            useFlexGap
                            justifyContent="center"
                        >
                            {data?.map((image) => (
                                <ImageWithDate
                                    image={image}
                                    extra={
                                        <Button
                                            color="error"
                                            size="small"
                                            sx={{ minWidth: 32 }}
                                            onClick={() => {
                                                restoreImage(
                                                    deviceId,
                                                    image.imagePath
                                                ).then(() => mutate());
                                            }}
                                        >
                                            <RestoreRounded />
                                        </Button>
                                    }
                                    onDelete={(image) => {
                                        forceDeleteImage(deviceId, image).then(
                                            () => mutate()
                                        );
                                    }}
                                />
                            ))}
                        </Stack>
                    </>
                )}
            </ModalWithCloseButton>
        </Stack>
    );
};
export default DeletedImages;

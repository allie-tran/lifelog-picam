import { ArchiveRounded, RestoreRounded } from '@mui/icons-material';
import {
    Button,
    CircularProgress,
    IconButton,
    Stack,
    Tooltip,
} from '@mui/material';
import { ImageObject } from '@utils/types';
import React from 'react';
import { useAppSelector } from 'reducers/hooks';
import useSWR from 'swr';
import { AccessLevel } from 'types/auth';
import {
    forceDeleteImage,
    getDeletedImages,
    restoreImage,
} from '../apis/browsing';
import ImageWithDate from './ImageWithDate';
import ModalWithCloseButton from './ModalWithCloseButton';

const DeletedImages = () => {
    const [open, setOpen] = React.useState(false);
    const deviceId = useAppSelector((state) => state.auth.deviceId) || '';
    const deviceAccess = useAppSelector((state) => state.auth.deviceAccess);

    const { data, isLoading, mutate } = useSWR(
        ['deleted-images', deviceId],
        () =>
            deviceAccess === AccessLevel.OWNER
                ? getDeletedImages(deviceId)
                : Promise.resolve([]),
        {
            revalidateOnFocus: false,
        }
    );

    return (
        <Stack direction="row" spacing={2} alignItems="center">
            <Tooltip title="Deleted Images">
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
            </Tooltip>
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

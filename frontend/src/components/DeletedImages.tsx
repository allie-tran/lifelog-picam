import { ArchiveRounded, RestoreRounded } from '@mui/icons-material';
import {
    Button,
    CircularProgress,
    IconButton,
    Pagination,
    Stack,
    Tooltip,
    Typography,
} from '@mui/material';
import { ImageObject } from '@utils/types';
import React from 'react';
import { useSearchParams } from 'react-router';
import { useAppSelector } from 'reducers/hooks';
import useSWR from 'swr';
import { AccessLevel } from 'types/auth';
import {
    forceDeleteImage,
    forceDeleteImages,
    getDeletedImages,
    restoreImage,
} from '../apis/browsing';
import ImageWithDate from './ImageWithDate';
import ModalWithCloseButton from './ModalWithCloseButton';

const IMAGES_PER_PAGE = 20;

const DeletedImages = () => {
    const [open, setOpen] = React.useState(false);
    const [searchParams] = useSearchParams();
    const device = searchParams.get('device') || '';
    const deviceAccess = useAppSelector((state) => state.auth.deviceAccess);
    const [page, setPage] = React.useState(1);

    const { data, isLoading, mutate } = useSWR(
        ['deleted-images', device],
        () =>
            deviceAccess === AccessLevel.OWNER ||
            deviceAccess === AccessLevel.ADMIN
                ? getDeletedImages(device)
                : Promise.resolve([]),
        {
            revalidateOnFocus: true,
        }
    );

    const totalPages = data ? Math.ceil(data.length / IMAGES_PER_PAGE) : 0;
    const paginatedData = data ? data.slice((page - 1) * IMAGES_PER_PAGE, page * IMAGES_PER_PAGE) : [];
    const totalDeleted = data ? data.length : 0;

    return (
        <>
            <Tooltip title="Deleted Images">
                <IconButton
                    size="large"
                    color="secondary"
                    onClick={() => {
                        mutate().then(() => {
                            setOpen(true);
                        });
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
                        <Typography variant="h6" align="center" gutterBottom>
                            Deleted Images ({totalDeleted})
                        </Typography>
                        <Stack
                            direction="row"
                            justifyContent="center"
                            alignItems="center"
                        >
                            <Button
                                variant="outlined"
                                color="error"
                                sx={{ mb: 2 }}
                                onClick={() => {
                                    forceDeleteImages(
                                        device,
                                        data.map(
                                            (image: ImageObject) =>
                                                image.imagePath
                                        )
                                    ).then(() => mutate());
                                }}
                            >
                                Delete All
                            </Button>
                            <Button
                                variant="outlined"
                                sx={{ mb: 2, ml: 2 }}
                                onClick={() => {
                                    data.forEach(
                                        (image: ImageObject, index: number) => {
                                            restoreImage(
                                                device,
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
                        </Stack>
                        <Stack
                            spacing={2}
                            sx={{ width: '100%', flexWrap: 'wrap' }}
                            direction="row"
                            useFlexGap
                            justifyContent="center"
                        >
                            {paginatedData.map((image: ImageObject) => (
                                <ImageWithDate
                                    height={200}
                                    fontSize="12px"
                                    image={image}
                                    extra={
                                        <Button
                                            size="small"
                                            sx={{ minWidth: 32 }}
                                            onClick={() => {
                                                restoreImage(
                                                    device,
                                                    image.imagePath
                                                ).then(() => mutate());
                                            }}
                                        >
                                            <RestoreRounded />
                                        </Button>
                                    }
                                    onDelete={(image) => {
                                        forceDeleteImage(device, image).then(
                                            () => mutate()
                                        );
                                    }}
                                />
                            ))}
                        </Stack>
                        <Pagination
                            count={totalPages}
                            page={page}
                            onChange={(e, value) => setPage(value)}
                            sx={{ display: 'flex', justifyContent: 'center', mt: 2 }}
                        />
                    </>
                )}
            </ModalWithCloseButton>
        </>
    );
};
export default DeletedImages;

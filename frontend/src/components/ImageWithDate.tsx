import { DeleteRounded, VideocamRounded } from '@mui/icons-material';
import { Box, Button, Stack, Typography } from '@mui/material';
import { THUMBNAIL_HOST_URL } from '../constants/urls';
import dayjs from 'dayjs';
import { deleteImage } from 'apis/browsing';
import { ImageObject } from '@utils/types';
import { useAppSelector } from 'reducers/hooks';
import { useEffect, useState } from 'react';

const ImageWithDate = ({
    image,
    onClick,
    extra,
    onDelete,
    height = '300px',
    fontSize,
    disableDelete = false,
    timeOnly = false,
}: {
    image: ImageObject;
    onClick?: () => void;
    extra?: React.ReactNode;
    onDelete?: (image: string) => void;
    height?: number | string;
    fontSize?: number | string;
    disableDelete?: boolean;
    timeOnly?: boolean;
}) => {
    const [deleted, setDeleted] = useState(false);
    const deviceId = useAppSelector((state) => state.auth.deviceId) || '';
    const imageUrl = `${THUMBNAIL_HOST_URL}/${deviceId}/${image.thumbnail}`;
    const formattedDate = timeOnly
        ? dayjs(image.timestamp).format('HH:mm')
        : dayjs(image.timestamp).format('DD MMM YYYY HH:mm');

    const handleDelete = async () => {
        setDeleted(true);
        await deleteImage(deviceId, image.imagePath);
        onDelete && onDelete(image.imagePath);
    };

    useEffect(() => {
        return () => {
            setDeleted(false);
        };
    }, [image.imagePath]);

    return (
        <Box
            sx={{
                marginBottom: '20px',
                height: height,
                position: 'relative',
                width: 'auto',
                opacity: deleted ? 0 : 1,
                transition: 'all .2s',
                visibility: deleted ? 'hidden' : 'visible',
            }}
        >
            <Box
                component="img"
                sx={{
                    position: 'relative',
                    cursor: onClick ? 'pointer' : 'default',
                    height: 'calc(100% - 24px)',
                    width: 'auto',
                    borderRadius: '8px',
                }}
                onClick={onClick}
                src={imageUrl}
                alt={image.imagePath}
            />
            <VideocamRounded
                sx={{
                    position: 'absolute',
                    top: 8,
                    left: 8,
                    color: 'white',
                    backgroundColor: 'rgba(0, 0, 0, 0.6)',
                    borderRadius: '50%',
                    padding: '4px',
                    display: image.isVideo ? 'block' : 'none',
                }}
                fontSize="medium"
                titleAccess="Video"
            />
            <Stack
                direction="row"
                spacing={1}
                sx={{
                    px: 0.5,
                }}
            >
                <Typography
                    sx={{
                        fontSize: fontSize || '14px',
                        userSelect: 'none',
                        backgroundColor: 'rgba(0, 0, 0, 0.6)',
                        color: 'white',
                        px: 1,
                        borderRadius: '4px',
                    }}
                >
                    {formattedDate}
                </Typography>
            </Stack>
            <Stack direction="row" spacing={0} alignItems="center">
                {!disableDelete && (
                    <Button
                        color="error"
                        size="small"
                        sx={{
                            fontSize: '12px',
                            minWidth: 24,
                        }}
                        onClick={handleDelete}
                    >
                        <DeleteRounded />
                    </Button>
                )}
                {extra}
            </Stack>
        </Box>
    );
};

export default ImageWithDate;

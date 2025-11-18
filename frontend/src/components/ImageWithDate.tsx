import { DeleteRounded, VideocamRounded } from '@mui/icons-material';
import { Box, Button, Stack, Typography } from '@mui/material';
import { THUMBNAIL_HOST_URL } from '../constants/urls';
import dayjs from 'dayjs';
import { deleteImage } from 'apis/browsing';
import { ImageObject } from '@utils/types';
import { useAppSelector } from 'reducers/hooks';

const ImageWithDate = ({
    image,
    onClick,
    extra,
    onDelete,
}: {
    image: ImageObject;
    onClick?: () => void;
    extra?: React.ReactNode;
    onDelete?: (image: string) => void;
}) => {
    const deviceId = useAppSelector((state) => state.auth.deviceId) || '';
    const imageUrl = `${THUMBNAIL_HOST_URL}/${deviceId}/${image.thumbnail}`;
    const formattedDate = dayjs(image.timestamp).format('lll');

    return (
        <Box
            sx={{
                marginBottom: '20px',
                height: '350px',
                position: 'relative',
                width: 'auto',
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
                alignItems="center"
                justifyContent="space-between"
                sx={{ marginTop: '4px' }}
            >
                <Typography>{formattedDate}</Typography>
                <Stack direction="row" spacing={1} alignItems="center">
                    <Button
                        color="error"
                        size="small"
                        sx={{ minWidth: 32 }}
                        onClick={() => {
                            deleteImage(deviceId, image.imagePath);
                            onDelete && onDelete(image.imagePath);
                        }}
                    >
                        <DeleteRounded />
                    </Button>
                    {extra}
                </Stack>
            </Stack>
        </Box>
    );
};

export default ImageWithDate;

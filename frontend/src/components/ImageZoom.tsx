import { DeleteRounded, DownloadRounded, ImageRounded } from '@mui/icons-material';
import { Box, Button, Stack } from '@mui/material';
import { useNavigate } from 'react-router';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import { clearZoomedImage } from 'reducers/zoomedImage';
import { deleteImage } from '../apis/browsing';
import { IMAGE_HOST_URL } from '../constants/urls';
import ModalWithCloseButton from './ModalWithCloseButton';

const ImageZoom = ({
    onDelete,
}: {
    onDelete?: (imgPath?: string) => void;
}) => {
    const dispatch = useAppDispatch();
    const navigate = useNavigate();
    const { image: imagePath, isVideo } = useAppSelector((state: any) => state.zoomedImage);

    const handleDownload = () => {
        const link = document.createElement('a');
        link.href = imagePath;
        link.download = imagePath.split('/').pop() || 'image.jpg';
        document.body.appendChild(link);
        link.click();
    };

    const handleDelete = () => {
        deleteImage(imagePath)
            .then(() => {
                dispatch(clearZoomedImage());
                onDelete && onDelete(imagePath);
            })
            .catch((err: any) => {
                console.error('Failed to delete image:', err);
            });
    };

    const handleSimilarImages = () => {
        dispatch(clearZoomedImage());
        navigate("/similar?image=" + encodeURIComponent(imagePath || ''));
    }
    if (!imagePath) {
        return null;
    }

    return (
        <ModalWithCloseButton open={true} onClose={() => dispatch(clearZoomedImage())}>
            <Stack
                direction="row"
                spacing={2}
                alignItems="center"
                marginBottom={2}
            >
                <Button variant="outlined"  onClick={handleSimilarImages}>
                    <ImageRounded sx={{ marginRight: 1 }} />
                    Similar Images
                </Button>
                <Button
                    onClick={handleDownload}
                    variant="outlined"
                    color="primary"
                >
                    <DownloadRounded sx={{ marginRight: 1 }} />
                    Download
                </Button>
                <Button variant="outlined" color="error" onClick={handleDelete}>
                    <DeleteRounded sx={{ marginRight: 1 }} />
                    Delete
                </Button>
            </Stack>
            {isVideo ? (
                <video
                    controls
                    autoPlay
                    style={{
                        maxWidth: '100%',
                        maxHeight: 'calc(80vh - 64px)',
                        borderRadius: '8px',
                        transform:  'rotate(90deg)',
                        transformOrigin: 'top left',
                    }}
                >
                    <source
                        src={`${IMAGE_HOST_URL}/${imagePath}`}
                        type="video/mp4"
                    />
                </video>
            ) : (
                <Box
                    component="img"
                    src={`${IMAGE_HOST_URL}/${imagePath}`}
                    alt="Zoomed"
                    sx={{
                        maxWidth: '100%',
                        maxHeight: 'calc(80vh - 64px)',
                        borderRadius: '8px',
                    }}
                />
            )}
        </ModalWithCloseButton>
    );
};

export { ImageZoom };

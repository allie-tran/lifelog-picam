import {
    DeleteRounded,
    DownloadRounded,
    ImageRounded,
} from '@mui/icons-material';
import { Button, CircularProgress, Stack } from '@mui/material';
import { useNavigate } from 'react-router';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import { clearZoomedImage } from 'reducers/zoomedImage';
import { deleteImage, getImage } from '../apis/browsing';
import { IMAGE_HOST_URL } from '../constants/urls';
import ModalWithCloseButton from './ModalWithCloseButton';
import useSWR from 'swr';

const ImageZoom = ({ onDelete }: { onDelete?: (imgPath?: string) => void }) => {
    const dispatch = useAppDispatch();
    const navigate = useNavigate();
    const deviceId = useAppSelector((state) => state.auth.deviceId) || '';
    const { image: imagePath, isVideo } = useAppSelector(
        (state: any) => state.zoomedImage
    );

    const { data: imageData, isLoading } = useSWR(imagePath, async () =>
        getImage(deviceId, imagePath || '')
    );

    const handleDownload = () => {
        const link = document.createElement('a');
        link.href = imagePath;
        link.download = imagePath.split('/').pop() || 'image.jpg';
        document.body.appendChild(link);
        link.click();
    };

    const handleDelete = () => {
        deleteImage(deviceId, imagePath)
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
        navigate('/similar?image=' + encodeURIComponent(imagePath || ''));
    };

    if (!imagePath) {
        return null;
    }

    console.log(imageData);

    return (
        <ModalWithCloseButton
            open={true}
            onClose={() => dispatch(clearZoomedImage())}
        >
            <Stack
                direction="row"
                spacing={2}
                alignItems="center"
                marginBottom={2}
            >
                <Button variant="outlined" onClick={handleSimilarImages}>
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
                        transform: 'rotate(90deg)',
                        transformOrigin: 'top left',
                    }}
                >
                    <source
                        src={`${IMAGE_HOST_URL}/${deviceId}/${imagePath}`}
                        type="video/mp4"
                    />
                </video>
            ) : isLoading ? (
                <CircularProgress size="3rem" />
            ) : (
                <img
                    src={imageData}
                    alt="Zoomed"
                    style={{
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

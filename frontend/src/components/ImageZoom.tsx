import { Box, Button, Stack } from '@mui/material';
import ModalWithCloseButton from './ModalWithCloseButton';
import { DeleteRounded, DownloadRounded } from '@mui/icons-material';
import { deleteImage } from '../apis/browsing';
import { IMAGE_HOST_URL } from '../constants/urls';

const ImageZoom = ({
    imagePath,
    onClose,
    onDelete,
}: {
    imagePath: string;
    onClose: () => void;
    onDelete?: () => void;
}) => {
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
                onClose();
                onDelete && onDelete();
            })
            .catch((err: any) => {
                console.error('Failed to delete image:', err);
            });
    };

    return (
        <ModalWithCloseButton open={true} onClose={onClose}>
            <Stack
                direction="row"
                spacing={2}
                alignItems="center"
                marginBottom={2}
            >
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
            <Box
                component="img"
                src={`${IMAGE_HOST_URL}/${imagePath}.jpg`}
                alt="Zoomed"
                sx={{
                    maxWidth: '100%',
                    maxHeight: 'calc(80vh - 64px)',
                    borderRadius: '8px',
                }}
            />
        </ModalWithCloseButton>
    );
};

export { ImageZoom };

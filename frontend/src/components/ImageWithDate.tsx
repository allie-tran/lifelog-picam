import { Box, Stack, Typography, useTheme } from '@mui/material';
import { THUMBNAIL_HOST_URL } from '../constants/urls';

const ImageWithDate = ({
    imagePath,
    timestamp,
    onClick,
    extra,
}: {
    imagePath: string;
    timestamp: string;
    onClick?: () => void;
    extra?: React.ReactNode;
}) => {
    const imageUrl = `${THUMBNAIL_HOST_URL}/${imagePath}.webp`;
    const date = new Date(timestamp);
    const formattedDate = date.toLocaleString();

    return (
        <Box
            sx={{
                marginBottom: '20px',
                height: '300px',
                position: 'relative',
                width: 'auto',
            }}
        >
            <Box
                component="img"
                sx={{
                    position: 'relative',
                    cursor: onClick ? 'pointer' : 'default',
                    height: '100%',
                    width: 'auto',
                    borderRadius: '8px',
                }}
                onClick={onClick}
                src={imageUrl}
                alt={imagePath}
            />
            <Stack
                direction="row"
                spacing={1}
                alignItems="center"
                justifyContent="space-between"
                sx={{ marginTop: '4px' }}
            >
                <Typography>{formattedDate}</Typography>
                {extra}
            </Stack>
        </Box>
    );
};

export default ImageWithDate;

import { AddRounded } from '@mui/icons-material';
import {
    Box,
    Button,
    Card,
    CardContent,
    Container,
    IconButton,
    Stack,
    Typography,
} from '@mui/material';
import { getWhiteList, removeFromWhiteList } from 'apis/browsing';
import FaceEnroll from 'components/FaceEnroll';
import ModalWithCloseButton from 'components/ModalWithCloseButton';
import React, { useEffect } from 'react';
import { useAppSelector } from 'reducers/hooks';
import useSWR from 'swr';

const WhiteListedPerson = ({
    name,
    images,
    onDelete,
}: {
    name: string;
    images: string[];
    onDelete?: () => void;
}) => {
    const [index, setIndex] = React.useState(0);

    useEffect(() => {
        if (images.length > 0) {
            setIndex(0);
        }
        // cycle through images every 5 seconds
        const interval = setInterval(() => {
            setIndex((prevIndex) => (prevIndex + 1) % images.length);
        }, 5000);
        return () => clearInterval(interval);
    }, [images]);

    return (
        <Stack alignItems="center" spacing={1} sx={{ width: 200 }}>
            <Card sx={{ margin: 1, width: '100%' }} elevation={3}>
                <CardContent>
                    <Stack alignItems="center" spacing={2} padding={0}>
                        <Typography
                            variant="subtitle1"
                            align="center"
                            sx={{ mb: 1 }}
                        >
                            <b> {name} </b>
                        </Typography>
                        {images.length > 0 && (
                            <img
                                src={images[index]}
                                alt={`${name} face`}
                                style={{ width: '100%', borderRadius: 8 }}
                            />
                        )}
                    </Stack>
                </CardContent>
            </Card>
            <Button
                variant="outlined"
                color="error"
                size="small"
                onClick={onDelete}
                sx={{ mt: 1 }}
            >
                Remove from White List
            </Button>
        </Stack>
    );
};

const FaceIntelligence = () => {
    const deviceId = useAppSelector((state) => state.auth.deviceId) || '';
    const [addingFace, setAddingFace] = React.useState(false);

    const { data, mutate } = useSWR(
        'get-white-list',
        async () => getWhiteList(deviceId),
        { refreshInterval: 5000 }
    );

    const handleDelete = async (name: string) => {
        removeFromWhiteList(deviceId, name);
        mutate();
    };

    return (
        <Container>
            <Typography variant="h6" gutterBottom color="primary">
                White List
            </Typography>
            <Typography variant="body2" gutterBottom>
                The white list contains faces that gave consent to be recognized
                by the system. Only faces in the white list will be allowed
                access. You can enroll new faces by clicking the button below.
            </Typography>
            {data && data.length === 0 && (
                <Typography variant="body1" gutterBottom>
                    No faces in the white list. Please enroll faces to allow
                    them access.
                </Typography>
            )}
            <Stack
                spacing={2}
                direction="row"
                flexWrap="wrap"
                sx={{
                    backgroundColor: '#1e1e1e',
                    padding: 2,
                    borderRadius: 2,
                }}
            >
                <DummyFaceCard onClick={() => setAddingFace(true)} />
                {data && data.length > 0 && (
                    <>
                        {data.map((entry) => (
                            <WhiteListedPerson
                                key={entry.name}
                                name={entry.name}
                                images={entry.images}
                                onDelete={() => handleDelete(entry.name)}
                            />
                        ))}
                    </>
                )}
            </Stack>
            {addingFace ? (
                <ModalWithCloseButton
                    open={addingFace}
                    onClose={() => setAddingFace(false)}
                >
                    <FaceEnroll
                        onUpdate={() => {
                            mutate();
                            setAddingFace(false);
                        }}
                    />
                    <Typography
                        variant="body1"
                        gutterBottom
                        sx={{ my: 2, width: '400px', color: 'text.secondary' }}
                    >
                        By enrolling yourself, you are giving consent for the
                        system to recognize your face until you choose to remove
                        it from the white list.
                    </Typography>
                </ModalWithCloseButton>
            ) : null}
        </Container>
    );
};

const DummyFaceCard = ({ onClick }: { onClick: () => void }) => {
    return (
        <Stack alignItems="center" spacing={1} sx={{ width: 200 }}>
            <Stack
                spacing={2}
                sx={{
                    p: 2,
                    border: '1px dashed',
                    borderColor: 'primary.main',
                    borderRadius: 1,
                    width: '100%',
                    '&:hover': {
                        backgroundColor: 'background.default',
                        cursor: 'pointer',
                    },
                }}
                onClick={onClick}
            >
                <Typography variant="subtitle1" align="center" sx={{ mb: 1 }}>
                    <b> Add New Face </b>
                </Typography>
                <Box
                    sx={{
                        backgroundColor: '#1e1e1e',
                        height: 228,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        borderRadius: 1,
                    }}
                >
                    <IconButton
                        color="primary"
                        disableRipple
                        sx={{
                            border: '1px dashed',
                            borderColor: 'primary.main',
                            alignSelf: 'center',
                        }}
                        size="large"
                    >
                        <AddRounded />
                    </IconButton>
                </Box>
            </Stack>
            <Button
                variant="outlined"
                color="primary"
                size="small"
                onClick={onClick}
                sx={{ mt: 1 }}
            >
                Enroll Face
            </Button>
        </Stack>
    );
};
export default FaceIntelligence;

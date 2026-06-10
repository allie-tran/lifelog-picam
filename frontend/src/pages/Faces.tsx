import { AddRounded, GroupsRounded } from '@mui/icons-material';
import {
    Box,
    Button,
    Card,
    CardContent,
    CircularProgress,
    Container,
    Divider,
    FormControlLabel,
    IconButton,
    Snackbar,
    Stack,
    Switch,
    Tooltip,
    Typography,
} from '@mui/material';
import {
    getImagesByPerson,
    getRecognitionMode,
    getWhiteList,
    relabelRecentFaces,
    removeFromWhiteList,
    setRecognitionMode,
} from 'apis/browsing';
import FaceClusters from 'components/FaceClusters';
import FaceEnroll from 'components/FaceEnroll';
import ModalWithCloseButton from 'components/ModalWithCloseButton';
import React, { useEffect } from 'react';
import { useSearchParams } from 'react-router';
import { THUMBNAIL_HOST_URL } from '../constants/urls';
import useSWR from 'swr';

// ---------------------------------------------------------------------------
// Person photos modal
// ---------------------------------------------------------------------------

const PersonPhotosModal = ({
    name,
    device,
    open,
    onClose,
}: {
    name: string;
    device: string;
    open: boolean;
    onClose: () => void;
}) => {
    const { data: photos, isLoading } = useSWR(
        open && device ? ['person-photos', device, name] : null,
        () => getImagesByPerson(device, name),
        { revalidateOnFocus: false }
    );

    return (
        <ModalWithCloseButton open={open} onClose={onClose}>
            <Box sx={{ width: { xs: '90vw', sm: 700 }, maxHeight: '80vh', display: 'flex', flexDirection: 'column' }}>
                <Typography variant="h6" fontWeight="bold" sx={{ mb: 2 }}>
                    {name} — {photos?.length ?? '…'} photos
                </Typography>
                {isLoading && <Typography variant="body2" color="text.secondary">Loading…</Typography>}
                {photos && photos.length === 0 && (
                    <Typography variant="body2" color="text.secondary">No photos found.</Typography>
                )}
                <Box sx={{ overflowY: 'auto', display: 'flex', flexWrap: 'wrap', gap: 0.75 }}>
                    {photos?.map((photo, i) => (
                        <Tooltip
                            key={i}
                            title={photo.timestamp ? new Date(photo.timestamp).toLocaleString() : ''}
                            placement="top"
                        >
                            <Box
                                component="img"
                                src={`${THUMBNAIL_HOST_URL}/${device}/${photo.thumbnail}`}
                                alt={photo.imagePath}
                                sx={{ width: 120, height: 90, objectFit: 'cover', borderRadius: 1 }}
                                onClick={() => window.open(`${THUMBNAIL_HOST_URL}/${device}/${photo.imagePath}`, '_blank')}
                            />
                        </Tooltip>
                    ))}
                </Box>
            </Box>
        </ModalWithCloseButton>
    );
};

// ---------------------------------------------------------------------------
// Whitelisted person card
// ---------------------------------------------------------------------------

const WhiteListedPerson = ({
    name,
    images,
    device,
    onDelete,
}: {
    name: string;
    images: string[];
    device: string;
    onDelete?: () => void;
}) => {
    const [index, setIndex] = React.useState(0);
    const [showPhotos, setShowPhotos] = React.useState(false);

    useEffect(() => {
        if (images.length === 0) return;
        setIndex(0);
        const interval = setInterval(() => {
            setIndex((prev) => (prev + 1) % images.length);
        }, 5000);
        return () => clearInterval(interval);
    }, [images]);

    return (
        <>
            <Stack alignItems="center" spacing={1} sx={{ width: 200, height: 345 }}>
                <Card
                    sx={{ margin: 1, width: '100%', cursor: 'pointer', '&:hover': { boxShadow: 6 } }}
                    elevation={3}
                    onClick={() => setShowPhotos(true)}
                >
                    <CardContent>
                        <Stack alignItems="center" spacing={2} padding={0}>
                            <Typography variant="subtitle1" align="center" sx={{ mb: 1 }}>
                                <b>{name}</b>
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
                <Button variant="outlined" color="error" size="small" onClick={onDelete} sx={{ mt: 1 }}>
                    Remove from White List
                </Button>
            </Stack>
            <PersonPhotosModal
                name={name}
                device={device}
                open={showPhotos}
                onClose={() => setShowPhotos(false)}
            />
        </>
    );
};

// ---------------------------------------------------------------------------
// Whitelist management section (only shown in whitelist mode)
// ---------------------------------------------------------------------------

const WhitelistSection = ({ device }: { device: string }) => {
    const [addingFace, setAddingFace] = React.useState(false);
    const [relabeling, setRelabeling] = React.useState(false);
    const [snackbar, setSnackbar] = React.useState<string | null>(null);

    const { data, mutate } = useSWR(
        device ? ['get-white-list', device] : null,
        () => getWhiteList(device),
        { refreshInterval: 60_000 }
    );

    const handleDelete = async (name: string) => {
        await removeFromWhiteList(device, name);
        mutate();
    };

    const handleRelabel = async () => {
        if (!device) return;
        setRelabeling(true);
        try {
            const result = await relabelRecentFaces(device, 24);
            setSnackbar(`Queued relabeling for ${result.queued} person(s) — thumbnails will update shortly.`);
        } catch {
            setSnackbar('Failed to queue relabeling.');
        } finally {
            setRelabeling(false);
        }
    };

    return (
        <>
            <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
                <Typography variant="h6" color="primary">
                    White List
                </Typography>
                <Tooltip title="Re-run face matching against the whitelist for images from the last 24 hours">
                    <span>
                        <Button
                            variant="outlined"
                            size="small"
                            disabled={relabeling || !device || !data?.length}
                            onClick={handleRelabel}
                            startIcon={relabeling ? <CircularProgress size={14} /> : undefined}
                        >
                            {relabeling ? 'Queuing…' : 'Relabel last 24h'}
                        </Button>
                    </span>
                </Tooltip>
            </Stack>
            <Typography variant="body2" gutterBottom>
                Only faces in the white list will be recognized. Click a card to browse their photos.
            </Typography>
            <Snackbar
                open={snackbar !== null}
                autoHideDuration={5000}
                onClose={() => setSnackbar(null)}
                message={snackbar}
            />
            {data && data.length === 0 && (
                <Typography variant="body1" gutterBottom>
                    No faces enrolled yet.
                </Typography>
            )}
            <Stack
                direction="row"
                flexWrap="wrap"
                spacing={2}
                sx={{ backgroundColor: 'background.paper', p: 2, borderRadius: 2 }}
            >
                <DummyFaceCard onClick={() => setAddingFace(true)} />
                {data?.map((entry) => (
                    <WhiteListedPerson
                        key={entry.name}
                        name={entry.name}
                        images={entry.images}
                        device={device}
                        onDelete={() => handleDelete(entry.name)}
                    />
                ))}
            </Stack>
            {addingFace && (
                <ModalWithCloseButton open={addingFace} onClose={() => setAddingFace(false)}>
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
                        By enrolling yourself, you are giving consent for the system to recognize
                        your face until you choose to remove it from the white list.
                    </Typography>
                </ModalWithCloseButton>
            )}
        </>
    );
};

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const FaceIntelligence = () => {
    const [searchParams] = useSearchParams();
    const device = searchParams.get('device') || '';
    const [toggling, setToggling] = React.useState(false);
    const [modeSnackbar, setModeSnackbar] = React.useState<string | null>(null);
    const [selectedPerson, setSelectedPerson] = React.useState<string | null>(null);

    const { data: modeData, mutate: mutateMode } = useSWR(
        device ? ['recognition-mode', device] : null,
        () => getRecognitionMode(device),
        { revalidateOnFocus: false }
    );

    const keepFaceRecognition = modeData?.keepFaceRecognition ?? false;

    const handleModeToggle = async (keep: boolean) => {
        if (!device) return;
        setToggling(true);
        try {
            await setRecognitionMode(device, keep);
            await mutateMode();
            setModeSnackbar(
                keep
                    ? 'Switched to whitelist mode — anonymous clusters cleared. Use "Relabel last 24h" to re-match recent faces.'
                    : 'Switched to anonymous clustering mode.'
            );
        } catch {
            setModeSnackbar('Failed to change mode.');
        } finally {
            setToggling(false);
        }
    };

    return (
        <Container maxWidth="md" sx={{ py: 4 }}>
            <Snackbar
                open={modeSnackbar !== null}
                autoHideDuration={7000}
                onClose={() => setModeSnackbar(null)}
                message={modeSnackbar}
            />

            {/* Mode toggle */}
            <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
                <Stack direction="row" alignItems="center" spacing={1}>
                    <GroupsRounded color="primary" />
                    <Typography variant="h6" color="primary">
                        Detected People
                    </Typography>
                </Stack>
                <FormControlLabel
                    control={
                        <Switch
                            checked={keepFaceRecognition}
                            disabled={toggling || !device}
                            onChange={(e) => handleModeToggle(e.target.checked)}
                            size="small"
                        />
                    }
                    label={
                        <Typography variant="caption">
                            {keepFaceRecognition ? 'Whitelist recognition' : 'Anonymous clustering'}
                        </Typography>
                    }
                    labelPlacement="start"
                />
            </Stack>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                {keepFaceRecognition
                    ? 'Faces matched against your white list.'
                    : 'Faces grouped by similarity. Toggle the switch to enable whitelist-based recognition.'}
            </Typography>

            <Box sx={{ mb: 3 }}>
                <FaceClusters onSelect={(name) => setSelectedPerson(name)} />
            </Box>

            {/* Whitelist management — only in whitelist mode */}
            {keepFaceRecognition && (
                <>
                    <Divider sx={{ my: 3 }} />
                    <WhitelistSection device={device} />
                </>
            )}
            {selectedPerson && (
                <PersonPhotosModal
                    name={selectedPerson}
                    device={device}
                    open={Boolean(selectedPerson)}
                    onClose={() => setSelectedPerson(null)}
                />
            )}
        </Container>
    );
};

// ---------------------------------------------------------------------------
// Add-face placeholder card
// ---------------------------------------------------------------------------

const DummyFaceCard = ({ onClick }: { onClick: () => void }) => (
    <Stack alignItems="center" spacing={1} sx={{ width: 200 }}>
        <Stack
            spacing={2}
            sx={{
                p: 2,
                border: '1px dashed',
                borderColor: 'primary.main',
                borderRadius: 1,
                width: '100%',
                '&:hover': { backgroundColor: 'background.default', cursor: 'pointer' },
            }}
            onClick={onClick}
        >
            <Typography variant="subtitle1" align="center" sx={{ mb: 1 }}>
                <b>Add New Face</b>
            </Typography>
            <Box
                sx={{
                    backgroundColor: 'background.paper',
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
                    sx={{ border: '1px dashed', borderColor: 'primary.main', alignSelf: 'center' }}
                    size="large"
                >
                    <AddRounded />
                </IconButton>
            </Box>
        </Stack>
        <Button variant="outlined" color="primary" size="small" onClick={onClick} sx={{ mt: 1 }}>
            Enroll Face
        </Button>
    </Stack>
);

export default FaceIntelligence;

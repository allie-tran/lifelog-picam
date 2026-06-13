import { getAllFaces } from '@apis/searchFilters';
import { Box, CircularProgress, Stack, Typography } from '@mui/material';
import { useSearchParams } from 'react-router';
import useSWR from 'swr';

type FaceCluster = { id: string; name: string; images: string[] };

const ClusterCard = ({ cluster, onClick }: { cluster: FaceCluster, onClick: (name: string) => void }) => (
    <Stack alignItems="center" spacing={1} sx={{ width: 140 }}>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, justifyContent: 'center' }}>
            {cluster.images.slice(0, 4).map((img, i) => (
                <Box
                    key={i}
                    component="img"
                    src={img}
                    alt="face"
                    onClick={() => onClick(cluster.name)}
                    sx={{
                        width: 60,
                        height: 60,
                        objectFit: 'cover',
                        borderRadius: '50%',
                        border: '2px solid',
                        borderColor: 'divider',
                    }}
                />
            ))}
        </Box>
        <Typography variant="caption" align="center" noWrap sx={{ maxWidth: 130 }}>
            {cluster.name}
        </Typography>
    </Stack>
);

const FaceClusters = ({ onSelect }: { onSelect: (name: string) => void }) => {
    const [searchParams] = useSearchParams();
    const device = searchParams.get('device') || '';

    const { data, isLoading } = useSWR(
        device ? [device, 'all-faces'] : null,
        () => getAllFaces(device),
        { revalidateOnFocus: false, refreshInterval: 60_000 }
    );

    if (isLoading) return <CircularProgress size={24} />;
    if (!data || data.length === 0) {
        return (
            <Typography variant="body2" color="text.secondary">
                No face groups detected yet.
            </Typography>
        );
    }

    return (
        <Stack direction="row" flexWrap="wrap" gap={2}>
            {data.map((cluster) => (
                <ClusterCard key={cluster.id} cluster={cluster} onClick={onSelect} />
            ))}
        </Stack>
    );
};

export default FaceClusters;

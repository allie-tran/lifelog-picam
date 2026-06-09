import { getAllFaces } from '@apis/searchFilters';
import { Stack, Typography } from '@mui/material';
import { useSearchParams } from 'react-router';
import useSWR from 'swr';

const FaceClusters = () => {
    const [searchParams] = useSearchParams();
    const device = searchParams.get('device') || '';
    const { data } = useSWR('/api/face-clusters', () =>
        getAllFaces(device)
    );

    if (!data) {
        return <div>Loading...</div>;
    }
    return (
        <Stack>
            {data.map((cluster) => (
                <Stack key={cluster.name}>
                    <Typography variant="h6">{cluster.name}</Typography>
                    <Stack direction="row" spacing={2}>
                        {cluster.images.map((img) => (
                            <img
                                key={img}
                                src={img}
                                alt="face"
                                style={{
                                    width: 100,
                                    height: 100,
                                    objectFit: 'cover',
                                    borderRadius: '50%',
                                }}
                            />
                        ))}
                    </Stack>
                </Stack>
            ))}
        </Stack>
    );
};

export default FaceClusters;

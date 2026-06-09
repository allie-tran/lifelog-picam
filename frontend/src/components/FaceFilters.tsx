import { getAllFaces } from '@apis/searchFilters';
import {
    Box,
    Button,
    Checkbox,
    FormControl,
    InputLabel,
    ListItemIcon,
    ListItemText,
    MenuItem,
    Select,
    Stack,
    Typography,
} from '@mui/material';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import { setSearchQuery } from 'reducers/search';
import { useSearchParams } from 'react-router';
import useSWR from 'swr';

const FaceFiltersHook = () => {
    const dispatch = useAppDispatch();
    const [searchParams] = useSearchParams();
    const device = searchParams.get('device') || '';
    const { peopleIds } = useAppSelector((state) => state.search.query);

    const { data: availableFaces } = useSWR(
        [device, 'faces'],
        async () => getAllFaces(device),
        { revalidateOnFocus: false, revalidateOnReconnect: false }
    );

    const nothingIsSelected = peopleIds.length === 0;

    const renderFilterOptions = () => (
        <Stack spacing={2}>
            <FormControl fullWidth variant="outlined">
                <InputLabel id="face-select-label">Faces</InputLabel>
                <Select
                    labelId="face-select-label"
                    multiple
                    value={peopleIds}
                    onChange={(e) => {
                        const value = e.target.value;
                        dispatch(
                            setSearchQuery({
                                peopleIds:
                                    typeof value === 'string'
                                        ? value.split(',')
                                        : value,
                            })
                        );
                    }}
                    renderValue={(selected) => selected.join(', ')}
                >
                    {availableFaces?.map((face) => (
                        <MenuItem key={face.id} value={face.id}>
                            <Checkbox checked={peopleIds.includes(face.id)} />
                            <ListItemIcon>
                                <img
                                    src={face.images[0]} // Assuming the first image represents the face
                                    alt={face.name}
                                    style={{
                                        marginRight: 8,
                                        width: 40,
                                        height: 40,
                                        objectFit: 'cover',
                                        borderRadius: '50%',
                                    }}
                                />
                            </ListItemIcon>
                            <ListItemText primary={face.name} />
                        </MenuItem>
                    ))}
                </Select>
            </FormControl>
        </Stack>
    );

    const renderFaceExplorer = () => (
        <Box sx={{ ml: 1, mt: 2 }}>
            <Typography fontWeight="bold">
                Selected Faces
            </Typography>
            {nothingIsSelected && (
                <Typography variant="caption" color="textSecondary">
                    Explore images containing the selected faces.
                </Typography>
            )}
            <Stack spacing={2} mt={2} direction="row" flexWrap="wrap">
                {availableFaces?.map((face) => {
                    if (!peopleIds.includes(face.id)) return null; // Only show selected faces
                    return (
                        <Stack
                            key={face.id}
                            direction="row"
                            spacing={2}
                            alignItems="center"
                        >
                            <img
                                src={face.images[0]} // Assuming the first image represents the face
                                alt={face.name}
                                style={{
                                    width: 30,
                                    height: 30,
                                    objectFit: 'cover',
                                    borderRadius: '50%',
                                }}
                            />
                            <span>{face.name}</span>
                        </Stack>
                    );
                })}
            </Stack>
        </Box>
    );

    const renderClearButton = () => {
        return (
            <Button
                disabled={nothingIsSelected}
                variant="outlined"
                color="primary"
                sx={{ mt: 2 }}
                onClick={() => {
                    dispatch(
                        setSearchQuery({
                            peopleIds: [],
                        })
                    );
                }}
            >
                Clear Filters
            </Button>
        );
    };

    return {
        renderFilterOptions,
        renderFaceExplorer,
        renderClearButton,
        nothingIsSelected,
    };
};

export { FaceFiltersHook };

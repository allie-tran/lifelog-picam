import { getAllFaces } from '@apis/searchFilters';
import {
    Button,
    Checkbox,
    FormControl,
    InputLabel,
    ListItemIcon,
    ListItemText,
    MenuItem,
    Select,
    Stack
} from '@mui/material';
import { useState } from 'react';
import { useAppSelector } from 'reducers/hooks';
import useSWR from 'swr';
import FaceClusters from './FaceClusters';


const FaceFiltersHook = () => {
    const deviceId = useAppSelector((state) => state.auth.deviceId);
    const [faces, setFaces] = useState<string[]>([]);

    const { data: availableFaces } = useSWR(
        [deviceId, 'faces'],
        async () => getAllFaces(deviceId),
        { revalidateOnFocus: false, revalidateOnReconnect: false }
    );

    const nothingIsSelected = faces.length === 0;

    const renderFilterOptions = () => (
        <Stack spacing={2}>
            <FormControl
                fullWidth
                variant="outlined"
            >
                <InputLabel id="face-select-label">Faces</InputLabel>
                <Select
                    labelId="face-select-label"
                    multiple
                    value={faces}
                    onChange={(e) => {
                        const value = e.target.value;
                        setFaces(typeof value === 'string' ? value.split(',') : value);
                    }}
                    renderValue={(selected) => selected.join(', ')}
                >
                    {availableFaces?.map((face) => (
                        <MenuItem key={face.name} value={face.name}>
                            <Checkbox checked={faces.indexOf(face.name) > -1} />
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

    const renderFaceExplorer = () => null;

    const renderClearButton = () => {
        return (
            <Button
                disabled={nothingIsSelected}
                variant="outlined"
                color="primary"
                sx={{ mt: 2 }}
                onClick={() => {
                    setFaces([]);
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

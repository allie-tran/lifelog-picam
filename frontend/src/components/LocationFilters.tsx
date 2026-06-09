import {
    getAvailableValues,
    getLocations,
    getMapMarkers,
    getMovingPeriods,
} from '@apis/searchFilters';
import {
    Box,
    Button,
    Checkbox,
    Chip,
    FormControl,
    Grid,
    InputLabel,
    ListItemText,
    MenuItem,
    Select,
    Stack,
    Typography,
} from '@mui/material';
import countryBoundingBoxes from 'country-bounding-boxes.json';
import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import useSWR from 'swr';
import MapSearch from './MapSearch';
import { setSearchQuery } from 'reducers/search';
// { countryCode: [countryName, [minLat, minLng, maxLat, maxLng]] }

const countryNameToBounds: Record<string, number[]> = {};
for (const entry of Object.values(countryBoundingBoxes)) {
    const [countryName, bounds] = entry as [string, number[]];
    countryNameToBounds[countryName] = [
        bounds[3],
        bounds[0],
        bounds[1],
        bounds[2],
    ]; // Convert to [minLat, minLng, maxLat, maxLng]
}

const getCountryBounds = (countries: string[]) => {
    const boundsList = countries
        .map((country) => countryNameToBounds[country])
        .filter(Boolean);

    if (boundsList.length === 0) return null;

    const minLat = Math.min(...boundsList.map((b) => b[0]));
    const minLng = Math.min(...boundsList.map((b) => b[1]));
    const maxLat = Math.max(...boundsList.map((b) => b[2]));
    const maxLng = Math.max(...boundsList.map((b) => b[3]));
    return [minLat, minLng, maxLat, maxLng] as [number, number, number, number];
};

const LocationFiltersHook = () => {
    const dispatch = useAppDispatch();
    const [searchParams] = useSearchParams();
    const device = searchParams.get('device') || '';
    const { isMoving, countries, locationIds, bounds } = useAppSelector(
        (state) => state.search.query
    );
    const [visualBounds, setVisualBounds] = useState<
        [number, number, number, number] | null
    >(null);

    const { data: availableCountries } = useSWR(
        [device, isMoving, 'country'],
        async () =>
            getAvailableValues(
                device,
                isMoving ? 'moving-cross-country' : 'country'
            ),
        { revalidateOnFocus: false, revalidateOnReconnect: false }
    );

    const { data: availableLocations } = useSWR(
        [device, 'location', countries, isMoving],
        async () =>
            isMoving
                ? getMovingPeriods(device, countries)
                : getLocations(device, countries),
        { revalidateOnFocus: false, revalidateOnReconnect: false }
    );

    const { data: markersData } = useSWR(
        [device, locationIds],
        async () => getMapMarkers(device, countries),
        
        { revalidateOnFocus: false, revalidateOnReconnect: false }
    );

    useEffect(() => {
        const newBounds = getCountryBounds(countries);
        setVisualBounds(newBounds);
        dispatch(setSearchQuery({ locationIds: [] }));
    }, [countries]);

    const nothingIsSelected =
        locationIds.length === 0 && countries.length === 0 && bounds === null;

    const renderFilterOptions = () => (
        <Box>
            <Stack spacing={2} mt={1}>
                {bounds && (
                    <Chip
                        label={`Bounds: (${bounds[0].toFixed(
                            2
                        )}, ${bounds[1].toFixed(2)}) - (${bounds[2].toFixed(
                            2
                        )}, ${bounds[3].toFixed(2)})`}
                        sx={{ mt: 1 }}
                    />
                )}
            </Stack>
            <CheckboxWithText
                label="On the Move"
                checked={isMoving}
                onChange={(checked) =>
                    dispatch(setSearchQuery({ isMoving: checked }))
                }
            />
            <FormControl sx={{ mt: 1, width: '100%' }}>
                <InputLabel id="country-select-label">Countries</InputLabel>
                <Select
                    labelId="country-select-label"
                    multiple
                    value={countries}
                    onChange={(e) =>
                        dispatch(
                            setSearchQuery({
                                countries:
                                    typeof e.target.value === 'string'
                                        ? e.target.value.split(',')
                                        : e.target.value,
                            })
                        )
                    }
                    renderValue={(selected) => selected.join(', ')}
                >
                    {availableCountries?.map((loc) => (
                        <MenuItem key={loc} value={loc}>
                            <Checkbox checked={countries.includes(loc)} />
                            <ListItemText primary={loc} />
                        </MenuItem>
                    ))}
                </Select>
            </FormControl>
            <FormControl sx={{ mt: 1, width: '100%' }}>
                <InputLabel id="location-select-label">Locations</InputLabel>
                <Select
                    labelId="location-select-label"
                    multiple
                    value={locationIds}
                    onChange={(e) =>
                        dispatch(
                            setSearchQuery({
                                locationIds:
                                    typeof e.target.value === 'string'
                                        ? e.target.value.split(',')
                                        : e.target.value,
                            })
                        )
                    }
                    renderValue={(selected) =>
                        availableLocations
                            ?.filter((loc) => selected.includes(loc.id as string))
                            .map((loc) => loc.name)
                            .join(', ') || ''
                    }
                >
                    {availableLocations?.map((loc) => (
                        <MenuItem key={loc.id} value={loc.id}>
                            <Checkbox
                                checked={locationIds.includes(loc.id as string)}
                            />
                            <ListItemText primary={loc.name} />
                        </MenuItem>
                    ))}
                </Select>
            </FormControl>
        </Box>
    );

    const handleAddBound = useCallback(
        (minLat: number, minLng: number, maxLat: number, maxLng: number) => {
            dispatch(
                setSearchQuery({ bounds: [minLat, minLng, maxLat, maxLng] })
            );
        },
        []
    );

    const renderMap = () => {
        return (
            <MapSearch
                visualBounds={visualBounds}
                onBoundsChange={handleAddBound}
                markersData={markersData || []}
            />
        );
    };

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
                            isMoving: false,
                            countries: [],
                            locationIds: [],
                            bounds: null,
                        })
                    );
                    setVisualBounds(null);
                }}
            >
                Clear Filters
            </Button>
        );
    };

    return {
        renderFilterOptions,
        renderMap,
        renderClearButton,
        nothingIsSelected,
    };
};

const CheckboxWithText = ({
    label,
    checked,
    onChange,
    disabled = false,
}: {
    label: string;
    checked: boolean;
    onChange: (checked: boolean) => void;
    disabled?: boolean;
}) => {
    if (!label) return null;
    return (
        <Grid size={4} sx={{ overflow: 'hidden', whiteSpace: 'nowrap' }}>
            <Checkbox
                size="small"
                disabled={disabled}
                checked={checked}
                onChange={(e) => onChange(e.target.checked)}
                sx={{ padding: '4px' }}
            />
            <Typography
                variant="caption"
                sx={{ display: 'inline-block', ml: -0.5 }}
            >
                {label.slice(0, 1).toUpperCase() + label.slice(1)}
            </Typography>
        </Grid>
    );
};

export { LocationFiltersHook };

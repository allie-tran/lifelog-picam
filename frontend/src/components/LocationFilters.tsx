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
    ListSubheader,
    MenuItem,
    Select,
    Stack,
    TextField,
    Typography,
} from '@mui/material';
import countryBoundingBoxes from 'country-bounding-boxes.json';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router';
import useSWR from 'swr';
import MapSearch from './MapSearch';
import { applyQueryToParams, parseSearchParams } from '@utils/searchParams';
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

const LocationFiltersHook = ({ extraLocationLabels = {} }: { extraLocationLabels?: Record<string, string> } = {}) => {
    const [searchParams, setSearchParams] = useSearchParams();
    const device = searchParams.get('device') || '';
    const { isMoving, countries, locationIds, bounds } = parseSearchParams(searchParams);
    const [locationSearch, setLocationSearch] = useState('');

    const update = useCallback((partial: Parameters<typeof applyQueryToParams>[0]) => {
        setSearchParams((prev) => applyQueryToParams(partial, new URLSearchParams(prev)));
    }, [setSearchParams]);
    const [visualBounds, setVisualBounds] = useState<
        [number, number, number, number] | null
    >(null);
    const isFirstRender = useRef(true);

    const { data: availableCountries } = useSWR(
        device ? [device, isMoving, 'country'] : null,
        async () =>
            getAvailableValues(
                device,
                isMoving ? 'moving-cross-country' : 'country'
            ),
        { revalidateOnFocus: false, revalidateOnReconnect: false }
    );

    const { data: availableLocations } = useSWR(
        device ? [device, 'location', countries, isMoving] : null,
        async () =>
            isMoving
                ? getMovingPeriods(device, countries)
                : getLocations(device, countries),
        { revalidateOnFocus: false, revalidateOnReconnect: false }
    );

    const { data: markersData } = useSWR(
        device ? [device, locationIds] : null,
        async () => getMapMarkers(device, countries),
        
        { revalidateOnFocus: false, revalidateOnReconnect: false }
    );

    const countriesKey = countries.join(',');
    useEffect(() => {
        const newBounds = getCountryBounds(countries);
        setVisualBounds(newBounds);
        // Skip clearing locationIds on initial mount so URL-loaded filters are preserved
        if (isFirstRender.current) {
            isFirstRender.current = false;
            return;
        }
        update({ locationIds: [] });
    }, [countriesKey]); // eslint-disable-line react-hooks/exhaustive-deps

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
                onChange={(checked) => update({ isMoving: checked })}
            />
            <FormControl sx={{ mt: 1, width: '100%' }}>
                <InputLabel id="country-select-label">Countries</InputLabel>
                <Select
                    labelId="country-select-label"
                    multiple
                    value={countries}
                    onChange={(e) =>
                        update({
                            countries:
                                typeof e.target.value === 'string'
                                    ? e.target.value.split(',')
                                    : e.target.value,
                        })
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
                        update({
                            locationIds:
                                typeof e.target.value === 'string'
                                    ? e.target.value.split(',')
                                    : e.target.value,
                        })
                    }
                    renderValue={(selected) =>
                        selected
                            .map((id) => {
                                const loc = availableLocations?.find((l) => l.id === id);
                                return loc?.name ?? extraLocationLabels[id] ?? id;
                            })
                            .join(', ')
                    }
                    MenuProps={{ autoFocus: false }}
                >
                    <ListSubheader sx={{ p: 0.5, lineHeight: 1 }}>
                        <TextField
                            size="small"
                            fullWidth
                            autoFocus
                            placeholder="Search locations…"
                            value={locationSearch}
                            onChange={(e) => setLocationSearch(e.target.value)}
                            onKeyDown={(e) => e.stopPropagation()}
                        />
                    </ListSubheader>
                    {locationIds
                        .filter(
                            (id) =>
                                !availableLocations?.some((l) => l.id === id) &&
                                (extraLocationLabels[id] ?? id)
                        )
                        .map((id) => (
                            <MenuItem key={id} value={id}>
                                <Checkbox checked />
                                <ListItemText primary={extraLocationLabels[id] ?? id} />
                            </MenuItem>
                        ))}
                    {(availableLocations ?? [])
                        .filter((loc) =>
                            !locationSearch ||
                            loc.name?.toLowerCase().includes(locationSearch.toLowerCase())
                        )
                        .map((loc) => (
                            <MenuItem key={loc.id} value={loc.id}>
                                <Checkbox checked={locationIds.includes(loc.id as string)} />
                                <ListItemText primary={loc.name} />
                            </MenuItem>
                        ))}
                </Select>
            </FormControl>
        </Box>
    );

    const handleAddBound = useCallback(
        (minLat: number, minLng: number, maxLat: number, maxLng: number) => {
            update({ bounds: [minLat, minLng, maxLat, maxLng] });
        },
        [update]
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
                    update({ isMoving: false, countries: [], locationIds: [], bounds: null });
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

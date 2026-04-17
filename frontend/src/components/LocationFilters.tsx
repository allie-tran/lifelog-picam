import { getAvailableValues, getLocations } from '@apis/searchFilters';
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
    Tab,
    Typography,
    styled
} from '@mui/material';
import countryBoundingBoxes from 'country-bounding-boxes.json';
import { useCallback, useEffect, useState } from 'react';
import { useAppSelector } from 'reducers/hooks';
import useSWR from 'swr';
import MapSearch from './MapSearch';
// { countryCode: [countryName, [minLat, minLng, maxLat, maxLng]] }

const countryNameToBounds: Record<string, number[]> = {};
for (const entry of Object.values(countryBoundingBoxes)) {
    const [countryName, bounds] = entry as [string, number[]];
    countryNameToBounds[countryName] = [bounds[3], bounds[0], bounds[1], bounds[2]]; // Convert to [minLat, minLng, maxLat, maxLng]
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
}

const LocationFiltersHook = () => {
    const deviceId = useAppSelector((state) => state.auth.deviceId);
    const [locations, setLocations] = useState<string[]>([]);
    const [countries, setCountries] = useState<string[]>([]);
    const [bounds, setBounds] = useState<
        [number, number, number, number] | null
    >(null);

    const [visualBounds, setVisualBounds] = useState<
        [number, number, number, number] | null
    >(null);

    const { data: availableCountries } = useSWR(
        [deviceId, 'country'],
        async () => getAvailableValues(deviceId, 'country'),
        { revalidateOnFocus: false, revalidateOnReconnect: false }
    );

    const { data: availableLocations } = useSWR(
        [deviceId, 'location', countries],
        async () => getLocations(deviceId, countries),
        { revalidateOnFocus: false, revalidateOnReconnect: false }
    );

    useEffect(() => {
        const newBounds = getCountryBounds(countries);
        setVisualBounds(newBounds);
        setLocations([]); // Clear locations when countries change
    }, [countries]);

    const nothingIsSelected = locations.length === 0 && countries.length === 0 && bounds === null;

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
            <FormControl sx={{ mt: 1, minWidth: 200 }}>
                <InputLabel id="country-select-label">Countries</InputLabel>
                <Select
                    labelId="country-select-label"
                    multiple
                    value={countries}
                    onChange={(e) =>
                        setCountries(
                            typeof e.target.value === 'string'
                                ? e.target.value.split(',')
                                : e.target.value
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
            <FormControl sx={{ mt: 1, minWidth: 200 }}>
                <InputLabel id="location-select-label">Locations</InputLabel>
                <Select
                    labelId="location-select-label"
                    multiple
                    value={locations}
                    onChange={(e) =>
                        setLocations(
                            typeof e.target.value === 'string'
                                ? e.target.value.split(',')
                                : e.target.value
                        )
                    }
                    renderValue={(selected) => selected.join(', ')}
                >
                    {availableLocations?.map((loc, idx) => (
                        <MenuItem key={idx} value={loc.name}>
                            <Checkbox checked={locations.includes(loc.name)} />
                            <ListItemText primary={loc.name} />
                        </MenuItem>
                    ))}
                </Select>
            </FormControl>
        </Box>
    );

    const handleAddBound = useCallback(
        (minLat: number, minLng: number, maxLat: number, maxLng: number) => {
            setBounds([minLat, minLng, maxLat, maxLng]);
        },
        []
    );

    const renderMap = () => {
        return <MapSearch 
            visualBounds={visualBounds}
        onBoundsChange={handleAddBound} />;
    };

    const renderClearButton = () => {
        return (
            <Button
                disabled={nothingIsSelected}
                variant="outlined"
                color="primary"
                sx={{ mt: 2 }}
                onClick={() => {
                    setCountries([]);
                    setLocations([]);
                    setBounds(null);
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

const ListOfCheckBoxes = ({
    options,
    selectedOptions,
    onChange,
}: {
    options: string[];
    selectedOptions: string[];
    onChange: (selected: string[]) => void;
}) => {
    return (
        <Grid container spacing={1} mt={1}>
            <CheckboxWithText
                label="All"
                checked={selectedOptions.length === options.length}
                onChange={(checked) => {
                    if (checked) {
                        onChange(options);
                    } else {
                        onChange([]);
                    }
                }}
            />
            {options.map((option) => (
                <CheckboxWithText
                    key={option}
                    label={option}
                    checked={selectedOptions.includes(option)}
                    onChange={(checked) => {
                        if (checked) {
                            onChange([...selectedOptions, option]);
                        } else {
                            onChange(
                                selectedOptions.filter((o) => o !== option)
                            );
                        }
                    }}
                />
            ))}
            <CheckboxWithText
                label="None"
                disabled={selectedOptions.length === 0}
                checked={false}
                onChange={(checked) => {
                    if (checked) {
                        onChange([]);
                    }
                }}
            />
        </Grid>
    );
};

const StyledTab = styled(Tab)({
    borderRadius: '8px px 0 0',
    marginRight: '4px',
    fontSize: '12px',
    minHeight: '32px',
    padding: '4px 12px',
    '&.Mui-selected': {
        backgroundColor: 'primary.main',
        color: 'primary.contrastText',
    },
});

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

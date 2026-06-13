import {
    getAvailableValues,
    getLocations,
    getMovingPeriods,
    searchLocations,
} from '@apis/searchFilters';
import {
    Box,
    Button,
    Checkbox,
    Chip,
    FormControl,
    Grid,
    InputAdornment,
    InputLabel,
    ListItemText,
    MenuItem,
    Select,
    TextField,
    Typography,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import countryBoundingBoxes from 'country-bounding-boxes.json';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { LocationData } from '@utils/types';
import { useSearchParams } from 'react-router';
import useSWR from 'swr';
import MapSearch from 'components/spatial/MapSearch';
import { applyQueryToParams, parseSearchParams } from '@utils/searchParams';
import { LocationSummaryItem } from 'apis/browsing';
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

const LocationFiltersHook = ({
    resultLocations = [],
    onAddLocationFilter,
    highlightedLocationId,
}: {
    resultLocations?: LocationSummaryItem[];
    onAddLocationFilter?: (id: string, name: string) => void;
    highlightedLocationId?: string | null;
} = {}) => {
    const [searchParams, setSearchParams] = useSearchParams();
    const device = searchParams.get('device') || '';
    const { isMoving, countries, locationIds, bounds } = parseSearchParams(searchParams);
    const [locationSearch, setLocationSearch] = useState('');
    const [debouncedSearch, setDebouncedSearch] = useState('');

    useEffect(() => {
        const t = setTimeout(() => setDebouncedSearch(locationSearch.trim()), 300);
        return () => clearTimeout(t);
    }, [locationSearch]);

    const locationLabels = useMemo<Record<string, string>>(() => {
        try { return JSON.parse(searchParams.get('locationLabels') || '{}'); }
        catch { return {}; }
    }, [searchParams]);

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

    const { data: searchResults } = useSWR(
        device && debouncedSearch.length >= 2 ? [device, 'location-search', debouncedSearch] : null,
        async () => searchLocations(device, debouncedSearch),
        { revalidateOnFocus: false, revalidateOnReconnect: false }
    );

    const displayedLocations: LocationData[] = debouncedSearch.length >= 2
        ? (searchResults ?? [])
        : (availableLocations ?? []);

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
            {bounds && (
                <Chip
                    icon={<span style={{ fontSize: 14, paddingLeft: 4 }}>🗺️</span>}
                    label={`Map area: ${bounds[0].toFixed(1)}°–${bounds[2].toFixed(1)}°N, ${bounds[1].toFixed(1)}°–${bounds[3].toFixed(1)}°E`}
                    color="secondary"
                    variant="outlined"
                    onDelete={() => update({ bounds: null })}
                    sx={{ mt: 1, maxWidth: '100%' }}
                />
            )}
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
            <TextField
                size="small"
                fullWidth
                sx={{ mt: 1 }}
                placeholder="Search places…"
                value={locationSearch}
                onChange={(e) => setLocationSearch(e.target.value)}
                slotProps={{
                    input: {
                        startAdornment: (
                            <InputAdornment position="start">
                                <SearchIcon fontSize="small" />
                            </InputAdornment>
                        ),
                    },
                }}
            />
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
                                const loc = displayedLocations.find((l) => l.id === id)
                                    ?? availableLocations?.find((l) => l.id === id);
                                return loc?.name ?? locationLabels[id] ?? id;
                            })
                            .join(', ')
                    }
                    MenuProps={{ autoFocus: false }}
                >
                    {locationIds
                        .filter((id) => !displayedLocations.some((l) => l.id === id))
                        .map((id) => (
                            <MenuItem key={id} value={id}>
                                <Checkbox checked />
                                <LocationMenuItem
                                    name={locationLabels[id] ?? id}
                                />
                            </MenuItem>
                        ))}
                    {displayedLocations.map((loc) => (
                        <MenuItem key={loc.id} value={loc.id}>
                            <Checkbox checked={locationIds.includes(loc.id as string)} />
                            <LocationMenuItem
                                name={loc.name ?? loc.id ?? ''}
                                address={loc.address}
                                suburb={loc.suburb}
                                city={loc.city}
                                country={loc.country}
                                categories={loc.categories}
                                count={loc.count}
                            />
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

    const handleClearBound = useCallback(() => {
        update({ bounds: null });
    }, [update]);

    const renderMap = () => {
        return (
            <MapSearch
                visualBounds={visualBounds}
                onBoundsChange={handleAddBound}
                onClearBounds={handleClearBound}
                resultLocations={resultLocations}
                onAddLocationFilter={onAddLocationFilter}
                highlightedLocationId={highlightedLocationId}
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

const LocationMenuItem = ({
    name,
    address,
    suburb,
    city,
    country,
    categories,
    count,
}: {
    name: string;
    address?: string | null;
    suburb?: string | null;
    city?: string | null;
    country?: string | null;
    categories?: string | null;
    count?: number | null;
}) => {
    const parts: string[] = [];
    if (suburb && suburb !== city) parts.push(suburb);
    if (city) parts.push(city);
    if (country) parts.push(country);
    const place = parts.join(', ');

    const firstCategory = categories?.split(';')[0]?.trim();
    const meta = [firstCategory, count != null ? `${count} visits` : null]
        .filter(Boolean)
        .join(' · ');

    // Show address only when it differs from the place hierarchy summary
    const showAddress = address && address !== place;

    return (
        <Box sx={{ minWidth: 0, overflow: 'hidden' }}>
            <Typography variant="body2" noWrap>{name}</Typography>
            {showAddress && (
                <Typography variant="caption" color="text.secondary" noWrap display="block">
                    {address}
                </Typography>
            )}
            {(place || meta) && (
                <Typography variant="caption" color="text.secondary" noWrap display="block">
                    {[place, meta].filter(Boolean).join(' · ')}
                </Typography>
            )}
        </Box>
    );
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

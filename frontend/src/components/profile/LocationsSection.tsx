import {
    AddRounded,
    DeleteRounded,
    HomeRounded,
    PlaceRounded,
    WorkRounded,
} from '@mui/icons-material';
import {
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    IconButton,
    InputAdornment,
    List,
    ListItemButton,
    ListItemText,
    Stack,
    Tab,
    Tabs,
    TextField,
    Tooltip,
    Typography,
} from '@mui/material';
import React from 'react';
import useSWR from 'swr';
import { useSearchParams } from 'react-router';
import {
    LabelKind,
    LabelRequest,
    LabeledLocation,
    StopOption,
    deleteLabel,
    getLabeledLocations,
    getStops,
    putLabel,
} from 'apis/profile';
import LocationPicker from 'components/profile/LocationPicker';

const KINDS: LabelKind[] = ['home', 'work', 'other'];

const kindIcon = (kind?: string | null) => {
    if (kind === 'home') return <HomeRounded fontSize="small" />;
    if (kind === 'work') return <WorkRounded fontSize="small" />;
    return <PlaceRounded fontSize="small" />;
};

const kindLabel = (kind: LabelKind) => kind.charAt(0).toUpperCase() + kind.slice(1);

type Coords = { latitude: number; longitude: number };

// ---------------------------------------------------------------------------
// Add / edit dialog
// ---------------------------------------------------------------------------

const LocationDialog = ({
    open,
    device,
    initial,
    onClose,
    onSave,
}: {
    open: boolean;
    device: string;
    initial?: LabeledLocation | null;
    onClose: () => void;
    onSave: (req: LabelRequest) => Promise<void>;
}) => {
    const [tab, setTab] = React.useState(0);
    const [kind, setKind] = React.useState<LabelKind>('home');
    const [label, setLabel] = React.useState('Home');
    const [name, setName] = React.useState('');
    const [locationId, setLocationId] = React.useState<string | null>(null);
    const [coords, setCoords] = React.useState<Coords | null>(null);
    const [stopFilter, setStopFilter] = React.useState('');
    const [saving, setSaving] = React.useState(false);

    const { data: stops } = useSWR(
        open && device ? ['stops', device] : null,
        () => getStops(device),
        { revalidateOnFocus: false }
    );

    React.useEffect(() => {
        if (!open) return;
        setSaving(false);
        setStopFilter('');
        if (initial) {
            setKind((initial.labelKind as LabelKind) ?? 'other');
            setLabel(initial.label);
            setName(initial.name ?? '');
            setLocationId(initial.locationId);
            setCoords(
                initial.latitude != null && initial.longitude != null
                    ? { latitude: initial.latitude, longitude: initial.longitude }
                    : null
            );
            // Edit existing → it's an already-resolved place; show the map tab.
            setTab(1);
        } else {
            setKind('home');
            setLabel('Home');
            setName('');
            setLocationId(null);
            setCoords(null);
            setTab(0);
        }
    }, [open, initial]);

    const setKindAndLabel = (k: LabelKind) => {
        setKind(k);
        if (k !== 'other' && (!label || KINDS.some((x) => kindLabel(x) === label))) {
            setLabel(kindLabel(k));
        }
    };

    const pickStop = (s: StopOption) => {
        setName(s.name);
        setLocationId(s.locationId);
        setCoords({ latitude: s.latitude, longitude: s.longitude });
    };

    const onPin = (c: Coords) => {
        setCoords(c);
        setLocationId(null); // moving the pin detaches from a detected stop
    };

    const filteredStops = (stops ?? []).filter((s) =>
        s.name.toLowerCase().includes(stopFilter.toLowerCase())
    );

    const canSave = label.trim().length > 0 && (locationId != null || coords != null);

    const handleSave = async () => {
        if (!canSave) return;
        setSaving(true);
        try {
            await onSave({
                locationId: locationId ?? undefined,
                label: label.trim(),
                labelKind: kind,
                name: name.trim() || undefined,
                latitude: coords?.latitude,
                longitude: coords?.longitude,
            });
        } finally {
            setSaving(false);
        }
    };

    return (
        <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
            <DialogTitle>{initial ? 'Edit label' : 'Add labeled location'}</DialogTitle>
            <DialogContent dividers>
                <Stack spacing={2}>
                    <Stack direction="row" spacing={1}>
                        {KINDS.map((k) => (
                            <Chip
                                key={k}
                                icon={kindIcon(k)}
                                label={kindLabel(k)}
                                color={kind === k ? 'primary' : 'default'}
                                onClick={() => setKindAndLabel(k)}
                                variant={kind === k ? 'filled' : 'outlined'}
                            />
                        ))}
                    </Stack>
                    <TextField
                        label="Label"
                        size="small"
                        value={label}
                        onChange={(e) => setLabel(e.target.value)}
                        fullWidth
                    />

                    <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="fullWidth">
                        <Tab label="Pick a place" />
                        <Tab label="Drop a pin" />
                    </Tabs>

                    {tab === 0 && (
                        <Box>
                            <TextField
                                placeholder="Search detected places…"
                                size="small"
                                fullWidth
                                value={stopFilter}
                                onChange={(e) => setStopFilter(e.target.value)}
                                InputProps={{
                                    startAdornment: (
                                        <InputAdornment position="start">
                                            <PlaceRounded fontSize="small" />
                                        </InputAdornment>
                                    ),
                                }}
                                sx={{ mb: 1 }}
                            />
                            <List dense sx={{ maxHeight: 240, overflowY: 'auto', border: '1px solid #eee', borderRadius: 1 }}>
                                {filteredStops.length === 0 && (
                                    <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
                                        No detected places{stopFilter ? ' match.' : ' yet.'}
                                    </Typography>
                                )}
                                {filteredStops.map((s) => (
                                    <ListItemButton
                                        key={s.locationId}
                                        selected={locationId === s.locationId}
                                        onClick={() => pickStop(s)}
                                    >
                                        <ListItemText
                                            primary={s.name}
                                            secondary={`${s.count} image${s.count !== 1 ? 's' : ''}${s.label ? ` · labeled "${s.label}"` : ''}${s.address ? ' · ' + s.address : ''}`}
                                        />
                                        {s.label && <Chip size="small" label={s.label} icon={kindIcon(s.labelKind)} />}
                                    </ListItemButton>
                                ))}
                            </List>
                        </Box>
                    )}

                    {tab === 1 && (
                        <Box>
                            <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
                                Click the map to drop a pin (drag to fine-tune).
                            </Typography>
                            <LocationPicker value={coords} onChange={onPin} />
                            <TextField
                                label="Place name (optional)"
                                size="small"
                                fullWidth
                                value={name}
                                onChange={(e) => setName(e.target.value)}
                                sx={{ mt: 2 }}
                            />
                        </Box>
                    )}

                    {coords && (
                        <Typography variant="caption" color="text.secondary">
                            📍 {coords.latitude.toFixed(5)}, {coords.longitude.toFixed(5)}
                            {name ? ` — ${name}` : ''}
                            {locationId ? ' · detected place' : ' · custom pin'}
                        </Typography>
                    )}
                </Stack>
            </DialogContent>
            <DialogActions>
                <Button onClick={onClose}>Cancel</Button>
                <Button variant="contained" disabled={!canSave || saving} onClick={handleSave}>
                    {saving ? 'Saving…' : 'Save'}
                </Button>
            </DialogActions>
        </Dialog>
    );
};

// ---------------------------------------------------------------------------
// Section
// ---------------------------------------------------------------------------

const LocationsSection = () => {
    const [searchParams] = useSearchParams();
    const device = searchParams.get('device') || '';
    const [dialogOpen, setDialogOpen] = React.useState(false);
    const [editing, setEditing] = React.useState<LabeledLocation | null>(null);

    const { data: locations, mutate } = useSWR('labeled-locations', getLabeledLocations, {
        revalidateOnFocus: false,
    });

    const handleSave = async (req: LabelRequest) => {
        await putLabel(req);
        await mutate();
        setDialogOpen(false);
        setEditing(null);
    };

    const handleDelete = async (locationId: string) => {
        await deleteLabel(locationId);
        await mutate();
    };

    return (
        <Box>
            <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
                <Stack direction="row" alignItems="center" spacing={1}>
                    <PlaceRounded color="primary" />
                    <Typography variant="h6" color="primary">
                        Labeled Locations
                    </Typography>
                </Stack>
                <Button
                    size="small"
                    variant="outlined"
                    startIcon={<AddRounded />}
                    onClick={() => {
                        setEditing(null);
                        setDialogOpen(true);
                    }}
                >
                    Add label
                </Button>
            </Stack>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                Tag places like Home and Work — pick from detected stops or drop a map pin.
                Labels show up across your timeline and map.
            </Typography>

            {locations && locations.length === 0 && (
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    No labeled locations yet.
                </Typography>
            )}

            <Stack direction="row" flexWrap="wrap" spacing={2} useFlexGap>
                {locations?.map((loc) => (
                    <Card key={loc.locationId} variant="outlined" sx={{ width: 240 }}>
                        <CardContent>
                            <Stack direction="row" alignItems="center" justifyContent="space-between">
                                <Stack direction="row" alignItems="center" spacing={1}>
                                    {kindIcon(loc.labelKind)}
                                    <Typography variant="subtitle1" fontWeight={700}>
                                        {loc.label}
                                    </Typography>
                                </Stack>
                                <Tooltip title="Remove">
                                    <IconButton size="small" color="error" onClick={() => handleDelete(loc.locationId)}>
                                        <DeleteRounded fontSize="small" />
                                    </IconButton>
                                </Tooltip>
                            </Stack>
                            <Box
                                sx={{ cursor: 'pointer', mt: 0.5 }}
                                onClick={() => {
                                    setEditing(loc);
                                    setDialogOpen(true);
                                }}
                            >
                                <Typography variant="body2" noWrap>
                                    {loc.name || 'Unnamed place'}
                                </Typography>
                                {loc.latitude != null && loc.longitude != null && (
                                    <Typography variant="caption" color="text.secondary">
                                        {loc.latitude.toFixed(4)}, {loc.longitude.toFixed(4)}
                                    </Typography>
                                )}
                            </Box>
                        </CardContent>
                    </Card>
                ))}
            </Stack>

            <LocationDialog
                open={dialogOpen}
                device={device}
                initial={editing}
                onClose={() => {
                    setDialogOpen(false);
                    setEditing(null);
                }}
                onSave={handleSave}
            />
        </Box>
    );
};

export default LocationsSection;

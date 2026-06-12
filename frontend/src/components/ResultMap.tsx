import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { useEffect } from 'react';
import { MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from 'react-leaflet';
import { LocationSummaryItem } from 'apis/browsing';
import { Box, Button, Stack, Typography } from '@mui/material';
import { PlaceRounded } from '@mui/icons-material';

type LocWithCoords = LocationSummaryItem & { latitude: number; longitude: number };

// ── colour helpers ─────────────────────────────────────────────────────────────

const STOP_COLORS = {
    small:  'rgba(59, 130, 246, 0.85)',
    medium: 'rgba(245, 158, 11, 0.85)',
    large:  'rgba(239, 68, 68, 0.85)',
};
const MOVE_COLOR = 'rgba(124, 58, 237, 0.85)';  // purple for transit

const stopColorForCount = (n: number) =>
    n >= 100 ? STOP_COLORS.large : n >= 20 ? STOP_COLORS.medium : STOP_COLORS.small;

// ── stop pill marker (existing style) ─────────────────────────────────────────

const createStopIcon = (name: string, count: number) => {
    const bg = stopColorForCount(count);
    const label = name.length > 20 ? name.slice(0, 19) + '…' : name;
    return L.divIcon({
        className: '',
        iconSize: [140, 46],
        iconAnchor: [70, 46],
        popupAnchor: [0, -50],
        html: `
            <div class="loc-label">
                <div class="loc-label-pill" style="background:${bg};">
                    <div class="loc-label-name">${label}</div>
                    <div class="loc-label-count">${count} image${count !== 1 ? 's' : ''}</div>
                </div>
                <div class="loc-label-stem" style="background:${bg};"></div>
                <div class="loc-label-dot" style="background:${bg};"></div>
            </div>`,
    });
};

// ── moving-period marker — dashed route pill with arrow ────────────────────────

const createMoveIcon = (name: string, count: number) => {
    const label = name.length > 24 ? name.slice(0, 23) + '…' : name;
    return L.divIcon({
        className: '',
        iconSize: [160, 36],
        iconAnchor: [80, 18],
        popupAnchor: [0, -24],
        html: `<div style="
            display:inline-flex;align-items:center;gap:5px;
            background:${MOVE_COLOR};
            border:2px dashed rgba(255,255,255,0.7);
            border-radius:20px;padding:4px 10px;
            box-shadow:0 2px 6px rgba(0,0,0,0.25);
            white-space:nowrap;max-width:160px;
        ">
            <span style="color:#fff;font-size:13px;">🚗</span>
            <div style="overflow:hidden;">
                <div style="color:#fff;font-size:11px;font-weight:700;font-family:sans-serif;line-height:1.2;max-width:110px;overflow:hidden;text-overflow:ellipsis;">${label}</div>
                <div style="color:rgba(255,255,255,0.8);font-size:10px;font-family:sans-serif;">${count} image${count !== 1 ? 's' : ''}</div>
            </div>
        </div>`,
    });
};

// ── fit helpers ────────────────────────────────────────────────────────────────

const FitBounds = ({ locations }: { locations: LocWithCoords[] }) => {
    const map = useMap();
    useEffect(() => {
        if (!locations.length) return;
        if (locations.length === 1) {
            map.setView([locations[0].latitude, locations[0].longitude], 14);
            return;
        }
        const bounds = L.latLngBounds(locations.map((l) => [l.latitude, l.longitude]));
        map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
    }, [map, locations]);
    return null;
};

// ── main component ─────────────────────────────────────────────────────────────

export const ResultMap = ({
    locations,
    onAddLocationFilter,
}: {
    locations: LocationSummaryItem[];
    onAddLocationFilter?: (id: string, name: string) => void;
}) => {
    const mapped = locations.filter(
        (l): l is LocWithCoords => l.latitude != null && l.longitude != null
    );

    if (!mapped.length) return null;

    // Separate stops and transit periods.
    const stops = mapped.filter((l) => l.stop !== false);
    const moves = mapped.filter((l) => l.stop === false);

    // Build the connecting polyline through all locations in order (chronological
    // from backend).  Only draw when we have both stops and transit points.
    const routeLine = mapped.length > 1 && moves.length > 0
        ? mapped.map((l) => [l.latitude, l.longitude] as [number, number])
        : null;

    return (
        <Box
            sx={{
                height: 300,
                width: '100%',
                borderRadius: 1,
                overflow: 'hidden',
                border: '1px solid',
                borderColor: 'divider',
                mb: 1,
            }}
        >
            <MapContainer
                center={[mapped[0].latitude, mapped[0].longitude]}
                zoom={13}
                scrollWheelZoom
                style={{ height: '100%', width: '100%' }}
            >
                <TileLayer url="https://api.maptiler.com/maps/dataviz-v4/{z}/{x}/{y}.png?key=bcAmE6kzFa3YgI6GTxUH" />
                <FitBounds locations={mapped} />

                {/* Dashed route polyline connecting all locations in sequence */}
                {routeLine && (
                    <Polyline
                        positions={routeLine}
                        pathOptions={{
                            color: MOVE_COLOR,
                            weight: 2,
                            dashArray: '6 5',
                            opacity: 0.7,
                        }}
                    />
                )}

                {/* Stop markers */}
                {stops.map((loc, i) => (
                    <Marker
                        key={loc.id ?? `stop-${i}`}
                        position={[loc.latitude, loc.longitude]}
                        icon={createStopIcon(loc.name, loc.count)}
                    >
                        <Popup>
                            <LocationPopup
                                loc={loc}
                                color={stopColorForCount(loc.count)}
                                onAddLocationFilter={onAddLocationFilter}
                            />
                        </Popup>
                    </Marker>
                ))}

                {/* Moving-period markers */}
                {moves.map((loc, i) => (
                    <Marker
                        key={loc.id ?? `move-${i}`}
                        position={[loc.latitude, loc.longitude]}
                        icon={createMoveIcon(loc.name, loc.count)}
                    >
                        <Popup>
                            <LocationPopup
                                loc={loc}
                                color={MOVE_COLOR}
                                label="In transit"
                                onAddLocationFilter={onAddLocationFilter}
                            />
                        </Popup>
                    </Marker>
                ))}
            </MapContainer>
        </Box>
    );
};

// ── shared popup ───────────────────────────────────────────────────────────────

function LocationPopup({
    loc,
    color,
    label,
    onAddLocationFilter,
}: {
    loc: LocWithCoords;
    color: string;
    label?: string;
    onAddLocationFilter?: (id: string, name: string) => void;
}) {
    return (
        <Box sx={{ minWidth: 140 }}>
            <Stack direction="row" alignItems="center" spacing={0.5} mb={0.5}>
                <PlaceRounded sx={{ fontSize: 14, color }} />
                <Typography fontWeight="bold" variant="body2">
                    {loc.name}
                </Typography>
            </Stack>
            {label && (
                <Typography variant="caption" color="text.secondary" display="block">
                    {label}
                </Typography>
            )}
            {loc.address && (
                <Typography variant="caption" color="text.secondary" display="block">
                    {loc.address}
                </Typography>
            )}
            <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>
                {loc.count} image{loc.count !== 1 ? 's' : ''}
            </Typography>
            {onAddLocationFilter && loc.id && loc.stop !== false && (
                <Button
                    size="small"
                    variant="outlined"
                    sx={{ mt: 1, textTransform: 'none', fontSize: 11 }}
                    onClick={() => onAddLocationFilter(loc.id!, loc.name)}
                >
                    Filter by this place
                </Button>
            )}
        </Box>
    );
}

import { Box, Button, Stack, Typography, useTheme } from '@mui/material';
import { PlaceRounded } from '@mui/icons-material';
import L from 'leaflet';
import icon from 'leaflet/dist/images/marker-icon.png';
import iconShadow from 'leaflet/dist/images/marker-shadow.png';
import 'leaflet/dist/leaflet.css';
import { useCallback, useEffect, useState } from 'react';
import { CircleMarker, MapContainer, Marker, Popup, TileLayer, useMap } from 'react-leaflet';
import {
    SelectArea,
    SelectAreaBounds,
    useSelectArea,
} from 'react-leaflet-select-area';
import MarkerClusterGroup from 'react-leaflet-markercluster';
import { LocationSummaryItem } from 'apis/browsing';
import { MAP_TILE_URL } from 'constants/urls';

let DefaultIcon = L.icon({
    iconUrl: icon,
    shadowUrl: iconShadow,
    iconSize: [25, 41],
    iconAnchor: [12, 41],
});
L.Marker.prototype.options.icon = DefaultIcon;

// ── Fit helpers ───────────────────────────────────────────────────────────────

function FitBounds({ bounds }: { bounds: [number, number, number, number] | null }) {
    const map = useMap();
    useEffect(() => {
        if (!bounds) return;
        map.fitBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]]);
    }, [map, bounds]);
    return null;
}

type LocWithCoords = LocationSummaryItem & { latitude: number; longitude: number };

const FitToResults = ({ locations }: { locations: LocWithCoords[] }) => {
    const map = useMap();
    useEffect(() => {
        if (!locations.length) return;
        if (locations.length === 1) {
            map.setView([locations[0].latitude, locations[0].longitude], 14);
            return;
        }
        const b = L.latLngBounds(locations.map((l) => [l.latitude, l.longitude]));
        map.fitBounds(b, { padding: [40, 40], maxZoom: 15 });
    }, [map, locations]);
    return null;
};

// ── Density circles ───────────────────────────────────────────────────────────

const DensityLayer = ({ locations }: { locations: LocWithCoords[] }) => {
    const maxCount = Math.max(...locations.map((l) => l.count), 1);
    return (
        <>
            {locations.map((loc, i) => {
                const t = loc.count / maxCount;
                const radius = 10 + Math.sqrt(loc.count / maxCount) * 40;
                const color = t >= 0.66
                    ? 'rgba(239,68,68,'
                    : t >= 0.33
                    ? 'rgba(245,158,11,'
                    : 'rgba(59,130,246,';
                return (
                    <CircleMarker
                        key={loc.id ?? `density-${i}`}
                        center={[loc.latitude, loc.longitude]}
                        radius={radius}
                        pathOptions={{
                            fillColor: `${color}0.25)`,
                            fillOpacity: 1,
                            weight: 1.5,
                            color: 'transparent',
                        }}
                    />
                );
            })}
        </>
    );
};

// ── Result location pill markers ──────────────────────────────────────────────

const LOC_COLORS = {
    small:  'rgba(59, 130, 246, 0.85)',
    medium: 'rgba(245, 158, 11, 0.85)',
    large:  'rgba(239, 68, 68, 0.85)',
};
const colorForCount = (n: number) =>
    n >= 100 ? LOC_COLORS.large : n >= 20 ? LOC_COLORS.medium : LOC_COLORS.small;

const createLocIcon = (name: string, count: number, highlighted = false) => {
    const bg = colorForCount(count);
    const label = name.length > 20 ? name.slice(0, 19) + '…' : name;
    const glow = highlighted
        ? `box-shadow:0 0 0 3px white,0 0 0 5px ${bg},0 0 12px 4px ${bg};`
        : '';
    return L.divIcon({
        className: '',
        iconSize: [140, 46],
        iconAnchor: [70, 46],
        popupAnchor: [0, -50],
        html: `<div class="loc-label">
            <div class="loc-label-pill" style="background:${bg};${glow}">
                <div class="loc-label-name">${label}</div>
                <div class="loc-label-count">${count} image${count !== 1 ? 's' : ''}</div>
            </div>
            <div class="loc-label-stem" style="background:${bg};"></div>
            <div class="loc-label-dot" style="background:${bg};"></div>
        </div>`,
    });
};

const CLUSTER_COLORS: Record<string, string> = {
    small:  'rgba(59,130,246,0.85)',
    medium: 'rgba(245,158,11,0.85)',
    large:  'rgba(239,68,68,0.85)',
};

const createClusterIcon = (cluster: any) => {
    const total = cluster.getAllChildMarkers().reduce((sum: number, m: any) => sum + (m.options.locCount || 0), 0);
    const cat = total >= 200 ? 'large' : total >= 50 ? 'medium' : 'small';
    const bg = CLUSTER_COLORS[cat];
    return L.divIcon({
        className: '',
        iconSize: L.point(40, 40),
        iconAnchor: L.point(20, 20),
        html: `<div style="
            width:40px;height:40px;border-radius:50%;
            background:${bg};border:2px solid rgba(255,255,255,0.9);
            box-shadow:0 2px 8px rgba(0,0,0,0.3);
            display:flex;align-items:center;justify-content:center;
            color:white;font-weight:700;font-size:12px;font-family:sans-serif;
        ">${total}</div>`,
    });
};

// ── Clear-bounds marker icon ──────────────────────────────────────────────────

const clearIcon = L.divIcon({
    className: '',
    iconSize: [26, 26],
    iconAnchor: [13, 13],
    html: `<div style="
        background:rgba(239,68,68,0.9);border:2px solid white;border-radius:50%;
        width:26px;height:26px;color:white;font-size:15px;font-weight:bold;
        display:flex;align-items:center;justify-content:center;
        box-shadow:0 2px 5px rgba(0,0,0,0.35);cursor:pointer;line-height:1;
    ">✕</div>`,
});

// ─────────────────────────────────────────────────────────────────────────────

const FlyToHighlighted = ({ locations, highlightedId }: { locations: LocWithCoords[]; highlightedId?: string | null }) => {
    const map = useMap();
    useEffect(() => {
        if (!highlightedId) return;
        const loc = locations.find((l) => l.id === highlightedId);
        if (loc) map.flyTo([loc.latitude, loc.longitude], Math.max(map.getZoom(), 13), { duration: 0.6 });
    }, [highlightedId, locations, map]);
    return null;
};

export function MapSearch({
    visualBounds,
    onBoundsChange,
    onClearBounds,
    resultLocations = [],
    onAddLocationFilter,
    highlightedLocationId,
}: {
    visualBounds: [number, number, number, number] | null;
    onBoundsChange: (minLat: number, minLng: number, maxLat: number, maxLng: number) => void;
    onClearBounds?: () => void;
    resultLocations?: LocationSummaryItem[];
    onAddLocationFilter?: (id: string, name: string) => void;
    highlightedLocationId?: string | null;
}) {
    const theme = useTheme();
    const controller = useSelectArea();
    const [activeBounds, setActiveBounds] = useState<SelectAreaBounds | null>(null);

    const resultMapped = resultLocations.filter(
        (l): l is LocWithCoords => l.latitude != null && l.longitude != null
    );

    const handleClearBounds = useCallback(() => {
        controller.clearSelection();
        setActiveBounds(null);
        onClearBounds?.();
    }, [controller, onClearBounds]);

    const handleBoundsChange = useCallback(
        (newBounds: SelectAreaBounds | null) => {
            setActiveBounds(newBounds);
            if (newBounds && onBoundsChange) {
                onBoundsChange(newBounds[0][0], newBounds[0][1], newBounds[1][0], newBounds[1][1]);
            }
        },
        [onBoundsChange]
    );

    return (
        <Box sx={{ height: '100%', width: '100%', border: '1px solid #ccc', borderRadius: 1, overflow: 'hidden' }}>
            <MapContainer
                center={[51.505, -0.09]}
                zoom={5}
                scrollWheelZoom
                style={{ height: '100%', width: '100%' }}
            >
                <TileLayer url={MAP_TILE_URL} />
                <FitBounds bounds={visualBounds} />
                {!visualBounds && resultMapped.length > 0 && (
                    <FitToResults locations={resultMapped} />
                )}
                <FlyToHighlighted locations={resultMapped} highlightedId={highlightedLocationId} />
                {(() => {
                    if (!highlightedLocationId) return null;
                    const loc = resultMapped.find((l) => l.id === highlightedLocationId);
                    if (!loc) return null;
                    return (
                        <Popup
                            position={[loc.latitude, loc.longitude]}
                            closeButton={false}
                            autoPan={false}
                        >
                            <Box sx={{ minWidth: 130 }}>
                                <Stack direction="row" alignItems="center" spacing={0.5} mb={0.5}>
                                    <PlaceRounded sx={{ fontSize: 13, color: colorForCount(loc.count) }} />
                                    <Typography fontWeight="bold" variant="body2">{loc.name}</Typography>
                                </Stack>
                                {loc.address && (
                                    <Typography variant="caption" color="text.secondary" display="block">{loc.address}</Typography>
                                )}
                                <Typography variant="caption" color="primary" display="block" sx={{ mt: 0.5 }}>
                                    {loc.count} photo{loc.count !== 1 ? 's' : ''}
                                </Typography>
                            </Box>
                        </Popup>
                    );
                })()}
                <SelectArea
                    keepRectangle
                    showControl
                    onBoundsChange={handleBoundsChange}
                    controller={controller}
                    options={{
                        color: theme.palette.secondary.main,
                        weight: 2,
                        dashArray: '10 5',
                    }}
                />
                {resultMapped.length > 0 && (
                    <>
                        <DensityLayer locations={resultMapped} />
                        <MarkerClusterGroup
                            iconCreateFunction={createClusterIcon}
                            showCoverageOnHover={false}
                            maxClusterRadius={80}
                            disableClusteringAtZoom={14}
                        >
                            {resultMapped.map((loc, i) => (
                                <Marker
                                    key={loc.id ?? `stop-${i}`}
                                    position={[loc.latitude, loc.longitude]}
                                    icon={createLocIcon(loc.name, loc.count, loc.id === highlightedLocationId)}
                                    {...({ locCount: loc.count } as any)}
                                >
                                    <Popup>
                                        <Box sx={{ minWidth: 140 }}>
                                            <Stack direction="row" alignItems="center" spacing={0.5} mb={0.5}>
                                                <PlaceRounded sx={{ fontSize: 14, color: colorForCount(loc.count) }} />
                                                <Typography fontWeight="bold" variant="body2">{loc.name}</Typography>
                                            </Stack>
                                            {loc.address && (
                                                <Typography variant="caption" color="text.secondary" display="block">{loc.address}</Typography>
                                            )}
                                            <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>
                                                {loc.count} image{loc.count !== 1 ? 's' : ''}
                                            </Typography>
                                            {onAddLocationFilter && loc.id && (
                                                <Button size="small" variant="outlined"
                                                    sx={{ mt: 1, textTransform: 'none', fontSize: 11 }}
                                                    onClick={() => onAddLocationFilter(loc.id!, loc.name)}
                                                >Filter by this place</Button>
                                            )}
                                        </Box>
                                    </Popup>
                                </Marker>
                            ))}
                        </MarkerClusterGroup>
                    </>
                )}
                {activeBounds && (
                    <Marker
                        position={activeBounds[1]}
                        icon={clearIcon}
                        eventHandlers={{ click: handleClearBounds }}
                        zIndexOffset={1000}
                    />
                )}
            </MapContainer>
        </Box>
    );
}
export default MapSearch;

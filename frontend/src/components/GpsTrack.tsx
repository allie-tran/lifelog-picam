import { Box, Typography } from '@mui/material';
import { GPSData, ResultSegment } from '@utils/types';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import React, { useEffect, useMemo, useRef } from 'react';
import {
    CircleMarker,
    MapContainer,
    Marker,
    Polyline,
    Popup,
    TileLayer,
    useMap,
} from 'react-leaflet';
import { useAppSelector } from 'reducers/hooks';

// ── Marker icons ────────────────────────────────────────────────────────────────

const PIN_COLORS = {
    small:  { bg: 'rgba(59, 130, 246, 0.85)',  hex: '#3b82f6' },
    medium: { bg: 'rgba(245, 158, 11, 0.85)',  hex: '#f59e0b' },
    large:  { bg: 'rgba(239, 68, 68, 0.85)',   hex: '#ef4444' },
};
const MOVE_COLOR = 'rgba(124, 58, 237, 0.85)';

const colorForCount = (n: number) =>
    n >= 100 ? PIN_COLORS.large : n >= 20 ? PIN_COLORS.medium : PIN_COLORS.small;

const MAP_PIN_PATH = 'M127.99414,15.9971a88.1046,88.1046,0,0,0-88,88c0,75.29688,80,132.17188,83.40625,134.55469a8.023,8.023,0,0,0,9.1875,0c3.40625-2.38281,83.40625-59.25781,83.40625-134.55469A88.10459,88.10459,0,0,0,127.99414,15.9971ZM128,72a32,32,0,1,1-32,32A31.99909,31.99909,0,0,1,128,72Z';

const makePinIcon = (hex: string, label: string) => L.divIcon({
    className: '',
    iconSize: [52, 60],
    iconAnchor: [26, 30],
    popupAnchor: [0, -64],
    html: `<div style="display:flex;flex-direction:column;align-items:center;gap:1px;">
        <svg width="28" height="34" viewBox="0 0 256 256" xmlns="http://www.w3.org/2000/svg"
             style="filter:drop-shadow(0 2px 3px rgba(0,0,0,0.3));">
            <path fill="${hex}" d="${MAP_PIN_PATH}"/>
        </svg>
        <div style="
            background:${hex};color:#fff;font-size:10px;font-weight:700;
            font-family:sans-serif;padding:2px 6px;border-radius:4px;
            box-shadow:0 1px 3px rgba(0,0,0,0.3);white-space:nowrap;
        ">${label}</div>
    </div>`,
});

const startIcon = makePinIcon('#22c55e', 'Start');
const endIcon   = makePinIcon('#ef4444', 'End');
const stopIcon  = makePinIcon('#6366f1', 'Stationary');

function haversineMetre(lat1: number, lon1: number, lat2: number, lon2: number): number {
    const R = 6371000;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) ** 2 +
        Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

const createLocIcon = (name: string, count: number) => {
    const { bg, hex } = colorForCount(count);
    const label = name.length > 20 ? name.slice(0, 19) + '…' : name;
    return L.divIcon({
        className: '',
        iconSize: [140, 62],
        iconAnchor: [70, 30],
        popupAnchor: [0, -36],
        html: `<div style="display:flex;flex-direction:column;align-items:center;gap:0;">
            <div class="loc-label-pill" style="background:${bg};">
                <div class="loc-label-name">${label}</div>
                <div class="loc-label-count">${count} image${count !== 1 ? 's' : ''}</div>
            </div>
        </div>`,
    });
};

const createMoveIcon = (name: string) => {
    const label = name.length > 24 ? name.slice(0, 23) + '…' : name;
    return L.divIcon({
        className: '',
        iconSize: [160, 32],
        iconAnchor: [80, 16],
        popupAnchor: [0, -20],
        html: `<div style="
            display:inline-flex;align-items:center;gap:5px;
            background:${MOVE_COLOR};
            border:2px dashed rgba(255,255,255,0.7);
            border-radius:20px;padding:3px 10px;
            box-shadow:0 2px 6px rgba(0,0,0,0.25);
            white-space:nowrap;max-width:160px;
        ">
            <span style="color:#fff;font-size:12px;">🚗</span>
            <div style="color:#fff;font-size:11px;font-weight:700;font-family:sans-serif;max-width:110px;overflow:hidden;text-overflow:ellipsis;">${label}</div>
        </div>`,
    });
};

// ── Stop / move layers ────────────────────────────────────────────────────────

type StopEntry = { lat: number; lon: number; name: string; count: number };
type MoveEntry = { pts: [number, number][]; name: string };

const StopLayer = ({ stops }: { stops: StopEntry[] }) => {
    const maxCount = Math.max(...stops.map((s) => s.count), 1);
    return (
        <>
            {stops.map((s, i) => {
                const t = s.count / maxCount;
                const radius = 10 + Math.sqrt(t) * 40;
                const color = t >= 0.66 ? 'rgba(239,68,68,' : t >= 0.33 ? 'rgba(245,158,11,' : 'rgba(59,130,246,';
                return (
                    <CircleMarker key={`heat-${i}`} center={[s.lat, s.lon]} radius={radius}
                        pathOptions={{ fillColor: `${color}0.2)`, fillOpacity: 1, weight: 0, color: 'transparent' }}
                    />
                );
            })}
            {stops.map((s, i) => (
                <Marker key={`stop-${i}`} position={[s.lat, s.lon]} icon={createLocIcon(s.name, s.count)}>
                    <Popup>
                        <Box sx={{ minWidth: 130 }}>
                            <Typography fontWeight="bold" variant="body2">{s.name}</Typography>
                            <Typography variant="caption" color="primary" display="block" sx={{ mt: 0.5 }}>
                                {s.count} photo{s.count !== 1 ? 's' : ''}
                            </Typography>
                        </Box>
                    </Popup>
                </Marker>
            ))}
        </>
    );
};

const MoveLayer = ({ moves }: { moves: MoveEntry[] }) => (
    <>
        {moves.map((m, i) => {
            if (m.pts.length < 2) return null;
            const mid = m.pts[Math.floor(m.pts.length / 2)];
            return (
                <React.Fragment key={`move-${i}`}>
                    <Polyline positions={m.pts}
                        pathOptions={{ color: MOVE_COLOR, weight: 2, dashArray: '6 5', opacity: 0.6 }}
                    />
                    <Marker position={mid} icon={createMoveIcon(m.name)}>
                        <Popup>
                            <Typography variant="body2" fontWeight="bold">{m.name}</Typography>
                            <Typography variant="caption" color="text.secondary">In transit</Typography>
                        </Popup>
                    </Marker>
                </React.Fragment>
            );
        })}
    </>
);

// ── Fit + track helpers ───────────────────────────────────────────────────────

function FitBounds({ positions, trackKey }: { positions: L.LatLngExpression[]; trackKey: string }) {
    const map = useMap();
    const posRef = useRef(positions);
    posRef.current = positions;
    useEffect(() => {
        if (posRef.current.length > 0)
            map.fitBounds(L.latLngBounds(posRef.current), { padding: [40, 40] });
    }, [map, trackKey]); // eslint-disable-line react-hooks/exhaustive-deps
    return null;
}

const TrackLine = ({
    gpsTrack,
    showMarkers,
    pathOptions,
    className,
}: {
    gpsTrack: GPSData[];
    showMarkers: boolean;
    pathOptions?: L.PolylineOptions;
    className?: string;
}) => {
    if (gpsTrack.length < 2) return null;
    const positions = gpsTrack.map((p) => [p.latitude, p.longitude] as L.LatLngExpression);
    const opts = pathOptions || { color: 'blue', weight: 3, opacity: 0.6 };
    const first = gpsTrack[0];
    const last  = gpsTrack[gpsTrack.length - 1];
    const isStop = showMarkers && haversineMetre(first.latitude, first.longitude, last.latitude, last.longitude) < 150;
    return (
        <>
            <Polyline positions={positions} pathOptions={opts} className={className} />
            {showMarkers && isStop && (
                <Marker position={positions[0]} icon={stopIcon} zIndexOffset={1000} />
            )}
            {showMarkers && !isStop && (
                <>
                    <Marker position={positions[0]} icon={startIcon} zIndexOffset={1000} />
                    <Marker position={positions[positions.length - 1]} icon={endIcon} zIndexOffset={1001} />
                </>
            )}
        </>
    );
};

// ── Main component ────────────────────────────────────────────────────────────

export function GpsTrackMap({
    imageGps = [],
    currentTrack = [],
    segments = [],
}: {
    imageGps?: GPSData[];
    currentTrack?: GPSData[];
    segments?: ResultSegment[];
}) {
    // const { GpsComponent } = GpsTrackerHook();
    const highlightedTrack = useAppSelector((state) => state.map.highlightedTrack);

    const allPositions = useMemo<L.LatLngExpression[]>(
        () => imageGps.map((p) => [p.latitude, p.longitude]),
        [imageGps]
    );

    const stops = useMemo<StopEntry[]>(() => {
        const map = new Map<string, StopEntry>();
        for (const seg of segments) {
            const loc = seg.location;
            if (!loc || loc.stop === false || loc.latitude == null || loc.longitude == null) continue;
            const key = loc.id ?? `${loc.latitude.toFixed(4)}_${loc.longitude.toFixed(4)}`;
            const existing = map.get(key);
            if (existing) existing.count += seg.images.length;
            else map.set(key, { lat: loc.latitude, lon: loc.longitude, name: loc.name ?? '', count: seg.images.length });
        }
        return Array.from(map.values());
    }, [segments]);

    const moves = useMemo<MoveEntry[]>(() =>
        segments
            .filter((seg) => seg.location?.stop === false && seg.gps?.length >= 2)
            .map((seg) => ({
                pts: seg.gps.map((p) => [p.latitude, p.longitude] as [number, number]),
                name: seg.location?.name ?? 'In transit',
            })),
        [segments]
    );

    const trackKey = (() => {
        const active = currentTrack.length ? currentTrack : imageGps;
        if (!active.length) return '';
        return `${active[0].timestamp}_${active[active.length - 1].timestamp}`;
    })();

    const center: L.LatLngExpression = currentTrack.length
        ? [currentTrack[currentTrack.length - 1].latitude, currentTrack[currentTrack.length - 1].longitude]
        : allPositions.length
        ? allPositions[allPositions.length - 1] as L.LatLngExpression
        : [0, 0];

    return (
        <Box sx={{ height: '100%', width: 400, border: '1px solid #ccc', borderRadius: 1, overflow: 'hidden' }}>
            <MapContainer center={center} zoom={13} scrollWheelZoom style={{ height: '100%', width: '100%' }}>
                <TileLayer
                    attribution="&copy; OpenStreetMap contributors"
                    url="https://api.maptiler.com/maps/dataviz-v4/{z}/{x}/{y}.png?key=bcAmE6kzFa3YgI6GTxUH"
                />
                <FitBounds
                    positions={currentTrack.length ? currentTrack.map((p) => [p.latitude, p.longitude]) : allPositions}
                    trackKey={trackKey}
                />

                {/* 1. Whole-day image GPS path */}
                {allPositions.length > 1 && (
                    <Polyline positions={allPositions} pathOptions={{ color: '#64748b', weight: 1.5, opacity: 0.35 }} />
                )}

                {/* 2. Stop heatmap + pill labels */}
                {stops.length > 0 && <StopLayer stops={stops} />}

                {/* 3. Move paths + pill labels */}
                {moves.length > 0 && <MoveLayer moves={moves} />}

                {/* 4. Current hour — animated direction-flow */}
                <TrackLine
                    gpsTrack={currentTrack}
                    showMarkers={false}
                    className="gps-direction-flow"
                    pathOptions={{ color: 'black', weight: 2, opacity: 1, dashArray: '10, 5', lineCap: 'round' }}
                />

                {/* 5. Highlighted segment — with start/end markers, on top */}
                <TrackLine
                    gpsTrack={highlightedTrack}
                    showMarkers={true}
                    pathOptions={{ color: '#4682B4', weight: 5, opacity: 1 }}
                />
            </MapContainer>
        </Box>
    );
}

export default GpsTrackMap;

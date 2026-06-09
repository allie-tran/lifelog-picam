import { useEffect, useMemo, useRef } from 'react';
import {
    MapContainer,
    TileLayer,
    Polyline,
    Marker,
    Popup,
    useMap,
} from 'react-leaflet';
import L from 'leaflet';
import { GPSData } from '@utils/types';
import { Box } from '@mui/material';
import 'leaflet/dist/leaflet.css';
import icon from 'leaflet/dist/images/marker-icon.png';
import iconShadow from 'leaflet/dist/images/marker-shadow.png';
import { useAppSelector } from 'reducers/hooks';
import GpsTrackerHook from './GpsTracker';

let DefaultIcon = L.icon({
    iconUrl: icon,
    shadowUrl: iconShadow,
    iconSize: [25, 41],
    iconAnchor: [12, 41],
});
L.Marker.prototype.options.icon = DefaultIcon;

// Interpolate between two hex colors by a 0–1 factor
function lerpColor(a: string, b: string, t: number): string {
    const parse = (hex: string) => [
        parseInt(hex.slice(1, 3), 16),
        parseInt(hex.slice(3, 5), 16),
        parseInt(hex.slice(5, 7), 16),
    ];
    const [ar, ag, ab] = parse(a);
    const [br, bg, bb] = parse(b);
    const r = Math.round(ar + (br - ar) * t);
    const g = Math.round(ag + (bg - ag) * t);
    const b_ = Math.round(ab + (bb - ab) * t);
    return `rgb(${r},${g},${b_})`;
}

// Multi-stop gradient: blue → cyan → green → yellow → orange → red
const GRADIENT_STOPS = [
    '#3b82f6',
    '#06b6d4',
    '#22c55e',
    '#eab308',
    '#f97316',
    '#ef4444',
];

function getGradientColor(t: number): string {
    const scaled = t * (GRADIENT_STOPS.length - 1);
    const idx = Math.min(Math.floor(scaled), GRADIENT_STOPS.length - 2);
    const localT = scaled - idx;
    return lerpColor(GRADIENT_STOPS[idx], GRADIENT_STOPS[idx + 1], localT);
}

function FitBounds({
    positions,
    trackKey,
}: {
    positions: L.LatLngExpression[];
    trackKey: string;
}) {
    const map = useMap();
    // Keep a ref so the effect always sees the latest positions without
    // needing them in the dependency array (which would re-fit on every render).
    const positionsRef = useRef(positions);
    positionsRef.current = positions;

    // Only fit when the track itself changes (trackKey), not on re-renders.
    // This means the user can freely pan/zoom without being snapped back.
    useEffect(() => {
        if (positionsRef.current.length > 0) {
            map.fitBounds(L.latLngBounds(positionsRef.current), {
                padding: [40, 40],
            });
        }
    }, [map, trackKey]); // eslint-disable-line react-hooks/exhaustive-deps

    return null;
}

export function GpsTrackMap({
    gpsTrack,
    currentTrack,
}: {
    gpsTrack: GPSData[];
    currentTrack: GPSData[];
}) {
    const { GpsComponent, currentPosition } = GpsTrackerHook();
    const highlightedTrack = useAppSelector(
        (state) => state.map.highlightedTrack
    );
    const segments = useMemo(() => {
        return gpsTrack.slice(0, -1).map((point, i) => {
            const t = i / (gpsTrack.length - 1);
            const next = gpsTrack[i + 1];
            return {
                positions: [
                    [point.latitude, point.longitude],
                    [next.latitude, next.longitude],
                ] as L.LatLngExpression[],
                color: getGradientColor(t),
            };
        });
    }, [gpsTrack]);

    const allPositions = useMemo<L.LatLngExpression[]>(
        () => gpsTrack?.map((p) => [p.latitude, p.longitude]) ?? [],
        [gpsTrack]
    );
    const currentPositions = useMemo<L.LatLngExpression[]>(
        () => currentTrack?.map((p) => [p.latitude, p.longitude]) ?? [],
        [currentTrack]
    );

    // Stable string key that changes only when the loaded track changes.
    // Derived from the active track's first + last timestamp so navigating
    // to a different day triggers a re-fit, but re-renders from
    // highlightedTrack / scroll events do not.
    const trackKey = useMemo(() => {
        const active = currentTrack?.length ? currentTrack : gpsTrack;
        if (!active?.length) return '';
        return `${active[0].timestamp}_${active[active.length - 1].timestamp}`;
    }, [gpsTrack, currentTrack]);

    let endPos: L.LatLngExpression | undefined;
    if (currentPositions.length > 0) {
        endPos = currentPositions[currentPositions.length - 1];
    } else if (allPositions.length > 0) {
        endPos = allPositions[allPositions.length - 1];
    }

    const currentPos = [
        currentPosition?.coords.latitude || 0,
        currentPosition?.coords.longitude || 0,
    ] as L.LatLngExpression;

    return (
        <Box
            sx={{
                height: '100%',
                width: 400,
                border: '1px solid #ccc',
                borderRadius: 1,
                overflow: 'hidden',
            }}
        >
            {GpsComponent()}
            <MapContainer
                center={endPos || currentPos}
                zoom={13}
                scrollWheelZoom={true}
                style={{ height: '100%', width: '100%' }}
            >
                {currentPosition && (
                    <Marker
                        position={[
                            currentPosition.coords.latitude,
                            currentPosition.coords.longitude,
                        ]}
                    >
                        <Popup>Current Position</Popup>
                    </Marker>
                )}
                <TileLayer
                    // url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    attribution="&copy; OpenStreetMap contributors"
                    url="https://api.maptiler.com/maps/dataviz-v4/{z}/{x}/{y}.png?key=bcAmE6kzFa3YgI6GTxUH"
                />
                <FitBounds
                    positions={
                        currentPositions.length > 0
                            ? currentPositions
                            : allPositions.length > 0
                              ? allPositions
                              : [currentPos]
                    }
                    trackKey={trackKey}
                />
                {/* Gradient segments */}
                {segments.map((seg, i) => (
                    <Polyline
                        key={i}
                        positions={seg.positions}
                        pathOptions={{
                            color: seg.color,
                            weight: 3,
                            opacity: 0.5,
                        }}
                    />
                ))}
                {/* Highlighted track overlay */}
                {highlightedTrack.length > 0 && (
                    <Tracks
                        gpsTrack={highlightedTrack}
                        showMarkers={true}
                        pathOptions={{
                            color: '#4682B4',
                            weight: 5,
                            opacity: 1,
                        }}
                    />
                )}
                {/* Current track overlay */}
                <Tracks
                    className="gps-direction-flow"
                    gpsTrack={currentTrack}
                    showMarkers={false}
                    pathOptions={{
                        className: 'gps-direction-flow',
                        color: 'black',
                        weight: 2,
                        opacity: 1,
                        dashArray: '10, 5',
                        lineCap: 'round',
                    }}
                />
            </MapContainer>
        </Box>
    );
}

const Tracks = ({
    className,
    gpsTrack,
    showMarkers,
    pathOptions,
}: {
    className?: string;
    gpsTrack: GPSData[];
    showMarkers: boolean;
    pathOptions?: L.PolylineOptions;
}) => {
    if (gpsTrack.length < 2) {
        return null;
    }
    const start = gpsTrack[0];
    const end = gpsTrack[gpsTrack.length - 1];
    if (showMarkers) {
        return (
            <>
                <Marker position={[start.latitude, start.longitude]}>
                    <Popup>
                        Start: {new Date(start.timestamp).toLocaleString()}
                    </Popup>
                </Marker>
                <Polyline
                    positions={gpsTrack.map((point) => [
                        point.latitude,
                        point.longitude,
                    ])}
                    pathOptions={
                        pathOptions || {
                            color: 'blue',
                            weight: 3,
                            opacity: 0.5,
                        }
                    }
                    className={className}
                />
                <Marker position={[end.latitude, end.longitude]}>
                    <Popup>
                        End: {new Date(end.timestamp).toLocaleString()}
                    </Popup>
                </Marker>
            </>
        );
    }
    return (
        <Polyline
            pane="markerPane"
            positions={gpsTrack.map((point) => [
                point.latitude,
                point.longitude,
            ])}
            pathOptions={
                pathOptions || { color: 'blue', weight: 3, opacity: 0.5 }
            }
            className={className}
        />
    );
};

export default GpsTrackMap;

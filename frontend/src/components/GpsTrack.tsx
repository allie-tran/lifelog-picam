import { useEffect, useMemo } from 'react';
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

let DefaultIcon = L.icon({
    iconUrl: icon,
    shadowUrl: iconShadow,
    iconSize: [25, 41],
    iconAnchor: [12, 41]
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

function FitBounds({ positions }: { positions: L.LatLngExpression[] }) {
    const map = useMap();
    useEffect(() => {
        if (positions.length > 0) {
            const bounds = L.latLngBounds(positions);
            map.fitBounds(bounds, { padding: [40, 40] });
        }
    }, [map, positions]);
    return null;
}

export function GpsTrackMap({ gpsTrack, currentTrack }: { gpsTrack: GPSData[]; currentTrack: GPSData[] }) {
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

    if (gpsTrack.length < 2) {
        return null;
    }

    const allPositions: L.LatLngExpression[] = gpsTrack.map((point) => [
        point.latitude,
        point.longitude,
    ]);

    const currentPositions: L.LatLngExpression[] = currentTrack.map((point) => [
        point.latitude,
        point.longitude,
    ]);

    const startPos = currentPositions.length > 0 ? currentPositions[0] : allPositions[0];
    const endPos = currentPositions.length > 0 ? currentPositions[currentPositions.length - 1] : allPositions[allPositions.length - 1];

    return (
        <Box sx={{ height: 300, width: '100%' }}>
            <MapContainer
                center={endPos}
                zoom={13}
                scrollWheelZoom={true}
                style={{ height: '100%', width: '100%' }}
            >
                <TileLayer
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    attribution="&copy; OpenStreetMap contributors"
                />
                <FitBounds positions={currentPositions.length > 0 ? currentPositions : allPositions} />
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
                {/* Current track overlay */}
                {currentPositions.length > 1 && (
                    <Polyline
                        positions={currentPositions}
                        pathOptions={{
                            color: '#000',
                            weight: 5,
                            opacity: 0.8,
                        }}
                    />
                )}
                {/* Start Marker */}
                <Marker position={startPos}>
                    <Popup>
                        Start:{' '}
                        {new Date(gpsTrack[0].timestamp).toLocaleString()}
                    </Popup>
                </Marker>
                {/* End Marker */}
                <Marker position={endPos}>
                    <Popup>
                        End:{' '}
                        {new Date(
                            gpsTrack[gpsTrack.length - 1].timestamp
                        ).toLocaleString()}
                    </Popup>
                </Marker>
            </MapContainer>
        </Box>
    );
}

export default GpsTrackMap;

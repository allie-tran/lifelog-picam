import { Box, Typography } from '@mui/material';
import { GPSData, ResultSegment } from '@utils/types';
import { DayStop } from 'apis/browsing';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { useEffect, useMemo, useRef } from 'react';
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
import { MAP_TILE_URL, MAP_TILE_ATTRIBUTION } from 'constants/urls';
import { colorForPlace } from '@utils/placeColors';

// ── Marker icons ────────────────────────────────────────────────────────────────
const createLocIcon = (name: string, count: number, active: boolean) => {
    const bg = colorForPlace(name);
    const label = name.length > 20 ? name.slice(0, 19) + '…' : name;
    const opacity = active ? 1 : 0.35;
    return L.divIcon({
        className: '',
        iconSize: [140, 62],
        iconAnchor: [70, 30],
        popupAnchor: [0, -36],
        html: `<div style="display:flex;flex-direction:column;align-items:center;gap:0;opacity:${opacity};">
            <div class="loc-label-pill" style="background:${bg};">
                <div class="loc-label-name">${label}</div>
                <div class="loc-label-count">${count} image${count !== 1 ? 's' : ''}</div>
            </div>
        </div>`,
    });
};

// ── Stop / move layers ────────────────────────────────────────────────────────

type StopEntry = {
    lat: number;
    lon: number;
    name: string;
    count: number;
    active: boolean;
};
const StopLayer = ({ stops }: { stops: StopEntry[] }) => {
    const maxCount = Math.max(...stops.map((s) => s.count), 1);
    return (
        <>
            {stops.map((s, i) => {
                const t = s.count / maxCount;
                const radius = 10 + Math.sqrt(t) * 40;
                const color = t >= 0.66
                    ? 'rgba(239,68,68,'
                    : t >= 0.33
                      ? 'rgba(245,158,11,'
                      : 'rgba(59,130,246,';
                const opacity = s.active ? 0.2 : 0.07;
                return (
                    <CircleMarker
                        key={`heat-${i}`}
                        center={[s.lat, s.lon]}
                        radius={radius}
                        pathOptions={{
                            fillColor: `${color}${opacity})`,
                            fillOpacity: 1,
                            weight: 0,
                            color: 'transparent',
                        }}
                    />
                );
            })}
            {stops.map((s, i) => (
                <Marker
                    key={`stop-${i}`}
                    position={[s.lat, s.lon]}
                    icon={createLocIcon(s.name, s.count, s.active)}
                >
                    <Popup>
                        <Box sx={{ minWidth: 130 }}>
                            <Typography fontWeight="bold" variant="body2">
                                {s.name}
                            </Typography>
                            <Typography
                                variant="caption"
                                color="primary"
                                display="block"
                                sx={{ mt: 0.5 }}
                            >
                                {s.count} photo{s.count !== 1 ? 's' : ''}
                            </Typography>
                        </Box>
                    </Popup>
                </Marker>
            ))}
        </>
    );
};

// ── Fit + track helpers ───────────────────────────────────────────────────────

function FitBounds({
    positions,
    trackKey,
}: {
    positions: L.LatLngExpression[];
    trackKey: string;
}) {
    const map = useMap();
    const posRef = useRef(positions);
    const hasFit = useRef(false);
    posRef.current = positions;
    useEffect(() => {
        if (!posRef.current.length) return;
        const bounds = L.latLngBounds(posRef.current);
        if (!hasFit.current) {
            hasFit.current = true;
            map.fitBounds(bounds, { padding: [40, 40] });
        } else {
            map.flyToBounds(bounds, { padding: [40, 40], duration: 0.5 });
        }
    }, [map, trackKey]); // eslint-disable-line react-hooks/exhaustive-deps
    return null;
}

const TrackLine = ({
    gpsTrack,
    pathOptions,
    className,
}: {
    gpsTrack: GPSData[];
    pathOptions?: L.PolylineOptions;
    className?: string;
}) => {
    if (gpsTrack.length < 2) return null;
    const positions = gpsTrack.map(
        (p) => [p.latitude, p.longitude] as L.LatLngExpression
    );
    const opts = pathOptions || { color: 'blue', weight: 3, opacity: 0.6 };
    return (
        <Polyline
            positions={positions}
            pathOptions={opts}
            className={className}
        />
    );
};

// ── Main component ────────────────────────────────────────────────────────────

export function GpsTrackMap({
    imageGps = [],
    fullTrack = [],
    currentTrack = [],
    segments = [],
    activeSegmentIds,
    dayStops = [],
}: {
    imageGps?: GPSData[];
    fullTrack?: GPSData[];
    currentTrack?: GPSData[];
    segments?: ResultSegment[];
    activeSegmentIds?: Set<number>;
    dayStops?: DayStop[];
}) {
    const highlightedTrack = useAppSelector(
        (state) => state.map.highlightedTrack
    );
    const hasActiveFilter =
        activeSegmentIds != null && activeSegmentIds.size > 0;

    // Whole-day path = the full raw GPS track (dense), falling back to the
    // sparse image-GPS points when no raw track exists for the day.
    const dayTrack = fullTrack.length > 1 ? fullTrack : imageGps;

    const allPositions = useMemo<L.LatLngExpression[]>(
        () => dayTrack.map((p) => [p.latitude, p.longitude]),
        [dayTrack]
    );

    const stops = useMemo<StopEntry[]>(() => {
        const map = new Map<string, StopEntry>();

        // Pills are always the whole day's stops — same set, label and count
        // regardless of selection. With no active filter everything is focused.
        for (const s of dayStops) {
            if (!s.stop) continue;
            if (s.latitude == null || s.longitude == null) continue;
            const key = `${s.latitude.toFixed(4)}_${s.longitude.toFixed(4)}`;
            if (!map.has(key)) {
                map.set(key, { lat: s.latitude, lon: s.longitude, name: s.name, count: s.count, active: !hasActiveFilter });
            }
        }

        // Selection only toggles focus (opacity) on existing pills — it never
        // adds pills or changes their counts.
        if (hasActiveFilter) {
            for (const seg of segments) {
                const loc = seg.location;
                if (
                    !loc ||
                    loc.stop !== true ||
                    loc.latitude == null ||
                    loc.longitude == null
                )
                    continue;
                if (seg.segmentId == null || !activeSegmentIds!.has(seg.segmentId))
                    continue;
                const key = `${loc.latitude.toFixed(4)}_${loc.longitude.toFixed(4)}`;
                const existing = map.get(key);
                if (existing) existing.active = true;
            }
        }
        return Array.from(map.values());
    }, [segments, dayStops, activeSegmentIds, hasActiveFilter]);

    const trackKey = (() => {
        const active = currentTrack.length ? currentTrack : imageGps;
        if (!active.length) return '';
        return `${active[0].timestamp}_${active[active.length - 1].timestamp}`;
    })();

    const center: L.LatLngExpression = currentTrack.length
        ? [
              currentTrack[currentTrack.length - 1].latitude,
              currentTrack[currentTrack.length - 1].longitude,
          ]
        : allPositions.length
          ? (allPositions[allPositions.length - 1] as L.LatLngExpression)
          : [0, 0];

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
            <MapContainer
                center={center}
                zoom={13}
                scrollWheelZoom
                style={{ height: '100%', width: '100%' }}
            >
                <TileLayer
                    attribution={MAP_TILE_ATTRIBUTION}
                    url={MAP_TILE_URL}
                />
                <FitBounds
                    positions={
                        currentTrack.length
                            ? currentTrack.map((p) => [p.latitude, p.longitude])
                            : allPositions
                    }
                    trackKey={trackKey}
                />

                {/* 1. Whole-day image GPS path */}
                {allPositions.length > 1 && (
                    <Polyline
                        positions={allPositions}
                        pathOptions={{
                            color: '#64748b',
                            weight: 1.5,
                            opacity: 0.35,
                        }}
                    />
                )}

                {/* 2. Stop heatmap + pill labels */}
                {stops.length > 0 && <StopLayer stops={stops} />}

                {/* 3. Current hour — animated direction-flow */}
                <TrackLine
                    gpsTrack={currentTrack}
                    className="gps-direction-flow"
                    pathOptions={{
                        color: 'black',
                        weight: 2,
                        opacity: 1,
                        dashArray: '10, 5',
                        lineCap: 'round',
                    }}
                />

                {/* 5. Highlighted segment — with start/end markers, on top */}
                <TrackLine
                    gpsTrack={highlightedTrack}
                    pathOptions={{ color: '#4682B4', weight: 5, opacity: 1 }}
                />
            </MapContainer>
        </Box>
    );
}

export default GpsTrackMap;

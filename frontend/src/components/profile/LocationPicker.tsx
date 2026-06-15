import { Box } from '@mui/material';
import L from 'leaflet';
import icon from 'leaflet/dist/images/marker-icon.png';
import iconShadow from 'leaflet/dist/images/marker-shadow.png';
import 'leaflet/dist/leaflet.css';
import { MapContainer, Marker, TileLayer, useMap, useMapEvents } from 'react-leaflet';
import { useEffect } from 'react';
import { MAP_TILE_URL } from 'constants/urls';

const DefaultIcon = L.icon({
    iconUrl: icon,
    shadowUrl: iconShadow,
    iconSize: [25, 41],
    iconAnchor: [12, 41],
});
L.Marker.prototype.options.icon = DefaultIcon;

type LatLng = { latitude: number; longitude: number };

function ClickToPlace({ onPick }: { onPick: (p: LatLng) => void }) {
    useMapEvents({
        click(e) {
            onPick({ latitude: e.latlng.lat, longitude: e.latlng.lng });
        },
    });
    return null;
}

function Recenter({ value }: { value: LatLng | null }) {
    const map = useMap();
    useEffect(() => {
        if (value) map.flyTo([value.latitude, value.longitude], Math.max(map.getZoom(), 14), { duration: 0.5 });
    }, [map, value]);
    return null;
}

export default function LocationPicker({
    value,
    onChange,
    height = 280,
}: {
    value: LatLng | null;
    onChange: (p: LatLng) => void;
    height?: number;
}) {
    const center: [number, number] = value
        ? [value.latitude, value.longitude]
        : [51.505, -0.09];

    return (
        <Box sx={{ height, width: '100%', border: '1px solid #ccc', borderRadius: 1, overflow: 'hidden' }}>
            <MapContainer center={center} zoom={value ? 14 : 4} scrollWheelZoom style={{ height: '100%', width: '100%' }}>
                <TileLayer url={MAP_TILE_URL} />
                <ClickToPlace onPick={onChange} />
                <Recenter value={value} />
                {value && (
                    <Marker
                        position={[value.latitude, value.longitude]}
                        draggable
                        eventHandlers={{
                            dragend(e) {
                                const m = e.target as L.Marker;
                                const { lat, lng } = m.getLatLng();
                                onChange({ latitude: lat, longitude: lng });
                            },
                        }}
                    />
                )}
            </MapContainer>
        </Box>
    );
}

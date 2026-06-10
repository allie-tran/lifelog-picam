import { Box, Button, useTheme } from '@mui/material';
import L from 'leaflet';
import icon from 'leaflet/dist/images/marker-icon.png';
import iconShadow from 'leaflet/dist/images/marker-shadow.png';
import 'leaflet/dist/leaflet.css';
import { useCallback, useEffect, useState } from 'react';
import { MapContainer, Marker, Popup, TileLayer, useMap } from 'react-leaflet';
import {
    SelectArea,
    SelectAreaBounds,
    useSelectArea,
} from 'react-leaflet-select-area';
import MarkerClusterGroup from 'react-leaflet-markercluster';

let DefaultIcon = L.icon({
    iconUrl: icon,
    shadowUrl: iconShadow,
    iconSize: [25, 41],
    iconAnchor: [12, 41],
});
L.Marker.prototype.options.icon = DefaultIcon;

function FitBounds({
    bounds,
}: {
    bounds: [number, number, number, number] | null;
}) {
    const map = useMap();
    useEffect(() => {
        if (bounds) {
            console.log('Fitting map to bounds:', bounds);
            map.fitBounds([
                [bounds[0], bounds[1]], // Southwest (minLat, minLng)
                [bounds[2], bounds[3]], // Northeast (maxLat, maxLng)
            ]);
        }
    }, [map, bounds]);
    return null;
}

// 2. Custom Cluster Icon Logic
const createClusterIcon = (cluster: any) => {
    const childMarkers = cluster.getAllChildMarkers();

    // Sum the 'count' stored in each marker's options
    const totalImages = childMarkers.reduce((sum: number, marker: any) => {
        return sum + (marker.options.imageCount || 0);
    }, 0);

    let category = 'small';
    if (totalImages > 50) category = 'medium';
    if (totalImages > 200) category = 'large';

    return L.divIcon({
        html: `<span>${totalImages}</span>`,
        className: `image-cluster cluster-${category}`,
        iconSize: L.point(40, 40),
    });
};

export function MapSearch({
    visualBounds,
    onBoundsChange,
    markersData,
}: {
    visualBounds: [number, number, number, number] | null;
    onBoundsChange: (
        minLat: number,
        minLng: number,
        maxLat: number,
        maxLng: number
    ) => void;
    markersData: {
        id: string;
        lat: number;
        lng: number;
        name: string;
        weight: number;
    }[];
}) {
    const theme = useTheme();
    const controller = useSelectArea();

    const handleBoundsChange = useCallback(
        (newBounds: SelectAreaBounds | null) => {
            if (newBounds && onBoundsChange) {
                onBoundsChange(
                    newBounds[0][0],
                    newBounds[0][1],
                    newBounds[1][0],
                    newBounds[1][1]
                );
            }
        },
        [onBoundsChange]
    );

    return (
        <>
            <Box
                sx={{
                    height: "100%",
                    width: '100%',
                    border: '1px solid #ccc',
                    borderRadius: 1,
                    overflow: 'hidden',
                    margin: 1,
                }}
            >
                <MapContainer
                    center={[51.505, -0.09]}
                    zoom={13}
                    scrollWheelZoom={true}
                    style={{ height: '100%', width: '100%' }}
                >
                    <FitBounds bounds={visualBounds} />
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
                    <TileLayer
                        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                        attribution="&copy; OpenStreetMap contributors"
                    />
                    <MarkerClusterGroup
                        iconCreateFunction={createClusterIcon}
                        showCoverageOnHover={false}
                        maxClusterRadius={60} // Adjust density
                    >
                        {markersData?.map((m) => {
                            if (!m || !m.lat || !m.lng) return null; // Skip invalid locations
                            return (
                                <Marker
                                    key={m.id}
                                    position={
                                        m.lat && m.lng
                                            ? [m.lat, m.lng]
                                            : undefined
                                    }
                                    // TRICK: Store the count in options so the clusterer can see it
                                    {...({ imageCount: m.weight } as any)}
                                >
                                    <Popup>
                                        <div className="p-2">
                                            <h3 className="font-bold border-b mb-1">
                                                {m.name}
                                            </h3>
                                            <p className="text-sm">
                                                {m.weight} images at this
                                                location
                                            </p>
                                            <button
                                                className="mt-2 text-blue-500 underline"
                                                onClick={() =>
                                                    console.log(
                                                        'Navigate to location:',
                                                        m.id
                                                    )
                                                }
                                            >
                                                View Images
                                            </button>
                                        </div>
                                    </Popup>
                                </Marker>
                            );
                        })}
                    </MarkerClusterGroup>
                </MapContainer>
                <Button
                    variant="outlined"
                    sx={{
                        position: 'absolute',
                        zIndex: 1000,
                        margin: 1,
                        right: 0,
                        top: 0,
                    }}
                    onClick={() => controller.clearSelection()}
                >
                    Clear Selection
                </Button>
            </Box>
        </>
    );
}
export default MapSearch;

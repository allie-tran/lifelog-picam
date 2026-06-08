import { processGPS, sendGPS } from '@apis/controls';
import {
    GpsFixedRounded,
    GpsOffRounded
} from '@mui/icons-material';
import {
    Button,
    Stack,
    Typography
} from '@mui/material';
import { parseErrorResponse } from '@utils/misc';
import { throttle } from 'lodash';
import React, { useEffect } from 'react';
import { useGeolocated } from 'react-geolocated';
import { useAppSelector } from 'reducers/hooks';

const GpsTrackerHook = () => {
    const user = useAppSelector((state) => state.auth.deviceId);
    const sensors = useAppSelector((state) => state.auth.sensors);
    const [disableGps, setDisableGps] = React.useState(true);
    const [secretDeviceId, setDeviceId] = React.useState<string | null>();
    const [isRegisteredDevice, setIsRegisteredDevice] = React.useState(false);
    const [currentPosition, setCurrentPosition] =
        React.useState<GeolocationPosition | null>(null);

    const { coords, isGeolocationAvailable, isGeolocationEnabled } =
        useGeolocated({
            positionOptions: {
                enableHighAccuracy: true,
            },
            watchPosition: true,
            userDecisionTimeout: 5000,
        });

    useEffect(() => {
        setDeviceId(navigator.userAgent);
        const isRegistered = sensors?.some(
            (sensor) => sensor.deviceId === navigator.userAgent
        );
        setIsRegisteredDevice(isRegistered);
        setDisableGps(!isRegistered);
    }, [sensors]);

    useEffect(() => {
        if (disableGps) {
            setCurrentPosition(null);
            return;
        }
        if (coords) {
            setCurrentPosition({
                coords: {
                    latitude: coords.latitude,
                    longitude: coords.longitude,
                    accuracy: coords.accuracy,
                    altitude: coords.altitude,
                    altitudeAccuracy: coords.altitudeAccuracy,
                    heading: coords.heading,
                    speed: coords.speed,
                },
                timestamp: Date.now(),
            });
            if (secretDeviceId) {
                throttle(
                    () =>
                        sendGPS(
                            coords.latitude,
                            coords.longitude,
                            coords.altitude || 0,
                            secretDeviceId,
                            new Date().toISOString()
                        ).catch((error) => {
                            const message = parseErrorResponse(error.response);
                            // alert('Error sending GPS data: ' + message);
                        }),
                    15000
                )();
                throttle(() => onProcessGps(), 60000)();
            }
        }
    }, [coords, secretDeviceId, disableGps]);

    const onProcessGps = () => {
        processGPS(
            user,
            new Date().toISOString().split('T')[0],
            secretDeviceId || ''
        )
            .then((response) => {
                console.log('GPS data processed:', response);
            })
            .catch((error) => {
                console.error('Error processing GPS data:', error);
            });
    };

    const DisableGpsButton = () => (
        <Button
            color={disableGps ? 'secondary' : 'primary'}
            onClick={() => setDisableGps(!disableGps)}
        >
            {disableGps ? 'Enable GPS' : 'Disable GPS'}
            {disableGps ? (
                <GpsOffRounded sx={{ ml: 1 }} />
            ) : (
                <GpsFixedRounded sx={{ ml: 1 }} />
            )}
        </Button>
    );

    const GpsInfo = () => {
        if (disableGps) {
            return null;
        }
        if (!isGeolocationAvailable) {
            return (
                <Typography variant="body1">
                    Your browser does not support Geolocation.
                </Typography>
            );
        } else if (!isGeolocationEnabled) {
            return (
                <Typography variant="body1">
                    Geolocation is not enabled. Please enable it to use this
                    feature.
                </Typography>
            );
        } else if (currentPosition) {
            return (
                <Stack>
                    <Typography variant="body1">
                        Sending location data for <b>{user}...</b>
                        {currentPosition.coords.latitude.toFixed(6)},{' '}
                        {currentPosition.coords.longitude.toFixed(6)}
                    </Typography>
                </Stack>
            );
        } else {
            return (
                <Typography variant="body1">
                    Getting the location data...
                </Typography>
            );
        }
    };

    const GpsComponent = () =>
        isRegisteredDevice ? (
            <Stack spacing={2} alignItems="center" sx={{ padding: 2 }}>
                <DisableGpsButton />
                <GpsInfo />
            </Stack>
        ) : null;

    return {
        currentPosition,
        isGeolocationAvailable,
        isGeolocationEnabled,
        GpsComponent,
    };
};

export default GpsTrackerHook;

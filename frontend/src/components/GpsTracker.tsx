import { processGPS, sendGPS } from '@apis/controls';
import {
    EditRounded,
    GpsFixedRounded,
    GpsOffRounded
} from '@mui/icons-material';
import {
    Button,
    IconButton,
    Stack,
    TextField,
    Typography,
} from '@mui/material';
import { parseErrorResponse } from '@utils/misc';
import { throttle } from 'lodash';
import React, { useEffect } from 'react';
import { useGeolocated } from 'react-geolocated';
import { useAppSelector } from 'reducers/hooks';

const GpsTrackerHook = () => {
    const device = useAppSelector((state) => state.auth.deviceId);
    const [disableGps, setDisableGps] = React.useState(true);
    const [changeDeviceId, setChangeDeviceId] = React.useState<boolean>(false);
    const [secretDeviceId, setDeviceId] = React.useState<string | null>(
        localStorage.getItem('deviceId') || null
    );
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
    }, [])

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
                            alert('Error sending GPS data: ' + message);
                        }),
                    10000
                )();
                // throttle(() => onProcessGps(), 60000)();
            }
        }
    }, [coords, secretDeviceId, disableGps]);

    // useEffect(() => {
    //     // save deviceId to local storage
    //     if (secretDeviceId) {
    //         localStorage.setItem('deviceId', secretDeviceId);
    //     }
    // }, [secretDeviceId]);

    const onProcessGps = () => {
        processGPS(
            device,
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
                    {/* {changeDeviceId ? ( */}
                    {/*     <TextField */}
                    {/*         label="Device ID" */}
                    {/*         value={secretDeviceId || ''} */}
                    {/*         onChange={(e) => setDeviceId(e.target.value)} */}
                    {/*     /> */}
                    {/* ) : ( */}
                    {/*     <Stack direction="row" alignItems="center" spacing={1}> */}
                    {/*         <Typography variant="body1"> */}
                    {/*             Device ID:{' '} */}
                    {/*             <strong> */}
                    {/*                 {secretDeviceId */}
                    {/*                     ? secretDeviceId.substring(0, 4) + '...' */}
                    {/*                     : 'Not Set'} */}
                    {/*             </strong> */}
                    {/*         </Typography> */}
                    {/*         <IconButton */}
                    {/*             onClick={() => setChangeDeviceId(true)} */}
                    {/*             color="primary" */}
                    {/*         > */}
                    {/*             <EditRounded /> */}
                    {/*         </IconButton> */}
                    {/*     </Stack> */}
                    {/* )} */}
                    <Typography variant="body1">
                        Current Location:{' '}
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

    const GpsComponent = () => (
        <Stack spacing={2} alignItems="center" sx={{ padding: 2 }}>
            <DisableGpsButton />
            <GpsInfo />
        </Stack>
    );

    return {
        currentPosition,
        isGeolocationAvailable,
        isGeolocationEnabled,
        GpsComponent,
    };
};

export default GpsTrackerHook;

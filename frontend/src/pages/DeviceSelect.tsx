import { CameraAltRounded } from '@mui/icons-material';
import { FormControl, InputLabel, MenuItem, Select } from '@mui/material';
import { setDeviceId } from 'reducers/auth';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import useSWR from 'swr';
import { getDevices } from '../apis/browsing';
import '../App.css';
import { useEffect } from 'react';
import { useSearchParams } from 'react-router';

const DeviceSelect = ({
    onChange,
}: {
    onChange?: (deviceId: string) => void;
}) => {
    const searchParams = useSearchParams();
    const deviceId = useAppSelector((state) => state.auth.deviceId) || '';
    const dispatch = useAppDispatch();

    const { data: devices, isLoading: devicesLoading } = useSWR(
        'devices-list',
        () => getDevices(),
        {
            revalidateOnFocus: false,
        }
    );

    useEffect(() => {
        if (devices && devices.length > 0) {
            if (deviceId && devices.includes(deviceId)) {
                return; // Current deviceId is valid
            }
            console.log('Auto-selecting device:', devices[0]);
            dispatch(setDeviceId(devices[0]));
            searchParams[0].set('device', devices[0]);
            onChange?.(devices[0]);
        }
    }, [devices, deviceId, onChange]);


    return (
        <FormControl fullWidth sx={{ width: '200px', pt: 1 }}>
            <InputLabel id="device-select-label">Device</InputLabel>
            <CameraAltRounded
                sx={{
                    position: 'absolute',
                    left: '12px',
                    top: '50%',
                    transform: 'translateY(-50%)',
                    zIndex: 1,
                    mt: '4px',
                }}
            />
            <Select
                sx={{ pl: '32px' }}
                labelId="device-select-label"
                value={deviceId || ''}
                label="Device"
                onChange={(e) => {
                    const selectedDeviceId = e.target.value;
                    dispatch(setDeviceId(selectedDeviceId));
                    onChange?.(selectedDeviceId);
                }}
                disabled={devicesLoading}
            >
                <MenuItem value="">All Devices</MenuItem>
                {devices?.map((device) => (
                    <MenuItem key={device} value={device}>
                        {device}
                    </MenuItem>
                ))}
            </Select>
        </FormControl>
    );
};
export default DeviceSelect;

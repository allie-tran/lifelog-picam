import { CameraAltRounded } from '@mui/icons-material';
import { FormControl, InputLabel, MenuItem, Select } from '@mui/material';
import { setDevice } from 'reducers/auth';
import { useAppDispatch } from 'reducers/hooks';
import useSWR from 'swr';
import { getDevices } from '../apis/browsing';
import '../App.css';
import { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router';

const DeviceSelect = ({
    onChange,
}: {
    onChange?: (device: string) => void;
}) => {
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const device = searchParams.get('device') || '';
    const dispatch = useAppDispatch();

    const { data: devices, isLoading: devicesLoading } = useSWR(
        'devices-list',
        () => getDevices(),
        {
            revalidateOnFocus: false,
        }
    );

    const selfOnChange = (newDevice: string) => {
        dispatch(setDevice(newDevice));
        searchParams.set('device', newDevice);
        navigate({ search: searchParams.toString() });
        onChange?.(newDevice);
    }

    useEffect(() => {
        if (devices && devices.length > 0) {
            if (device && devices.includes(device)) {
                return; // Current device is valid
            }
            selfOnChange(devices[0]);
        }
    }, [devices, device, onChange]);

    return (
        <FormControl sx={{ width: { xs: 130, sm: 200 } }} size="small">
            <InputLabel id="device-select-label">Device</InputLabel>
            <CameraAltRounded
                sx={{
                    position: 'absolute',
                    left: '12px',
                    top: '50%',
                    transform: 'translateY(-50%)',
                    zIndex: 1,
                    mt: '2px',
                }}
            />
            <Select
                sx={{ pl: '32px' }}
                labelId="device-select-label"
                value={device || ''}
                label="Content"
                onChange={(e) => {
                    selfOnChange(e.target.value);
                }}
                disabled={devicesLoading}
            >
                <MenuItem value="">All Devices</MenuItem>
                {devices?.map((d) => (
                    <MenuItem key={d} value={d}>
                        {d}
                    </MenuItem>
                ))}
            </Select>
        </FormControl>
    );
};
export default DeviceSelect;

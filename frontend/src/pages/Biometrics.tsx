import { Container, Stack } from '@mui/material';
import SensorHistory from 'components/Biometrics';
import CustomDatePicker from 'components/CustomDatePicker';
import DaySummaryComponent from 'components/DaySummary';
import { useEffect } from 'react';
import { useSearchParams } from 'react-router';
import { setDeviceId } from 'reducers/auth';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import useSWR from 'swr';
import '../App.css';
import { getAllDates } from '../apis/browsing';
import DeviceSelect from './DeviceSelect';

function Biometrics() {
    const [searchParams, _] = useSearchParams();
    const date = searchParams.get('date');
    const device = searchParams.get('device');
    const deviceId =
        useAppSelector((state) => state.auth.deviceId) || device || '';

    useEffect(() => {
        if (device) dispatch(setDeviceId(device));
    }, [device]);

    const dispatch = useAppDispatch();

    const { data: allDates } = useSWR(
        ['all-dates', deviceId, date],
        async () => {
            const allDates = await getAllDates(deviceId);
            return allDates;
        },
        {
            revalidateOnFocus: false,
        }
    );

    return (
        <>
            <Container>
                <Stack
                    direction="row"
                    spacing={2}
                    width="100%"
                    pl={1}
                    alignItems="center"
                    mb={2}
                >
                    <DeviceSelect />
                    <CustomDatePicker
                        date={date}
                        allDates={allDates}
                        setPage={() => {}}
                        setHour={() => {}}
                    />
                </Stack>
                <SensorHistory />
                <DaySummaryComponent />
            </Container>
        </>
    );
}

export default Biometrics;

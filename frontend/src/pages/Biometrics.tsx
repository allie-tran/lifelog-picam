import { Container, Stack } from '@mui/material';
import SensorHistory from 'components/Biometrics';
import CustomDatePicker from 'components/CustomDatePicker';
import DaySummaryComponent from 'components/DaySummary';
import { useEffect } from 'react';
import { useSearchParams } from 'react-router';
import { setDevice } from 'reducers/auth';
import { useAppDispatch } from 'reducers/hooks';
import useSWR from 'swr';
import '../App.css';
import { getAllDates } from '../apis/browsing';
import DeviceSelect from './DeviceSelect';

function Biometrics() {
    const [searchParams, _] = useSearchParams();
    const date = searchParams.get('date');
    const device = searchParams.get('device') || '';

    const dispatch = useAppDispatch();

    useEffect(() => {
        if (device) dispatch(setDevice(device));
    }, [device]);

    const { data: allDates } = useSWR(
        ['all-dates', device, date],
        async () => {
            const allDates = await getAllDates(device);
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

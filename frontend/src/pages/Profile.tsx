import { Container, Divider } from '@mui/material';
import { useSearchParams } from 'react-router';
import PeopleSection from 'components/profile/PeopleSection';
import LocationsSection from 'components/profile/LocationsSection';
import DevicesSection from 'components/profile/DevicesSection';
import MealTimesSection from 'components/profile/MealTimesSection';

const Profile = () => {
    const [searchParams] = useSearchParams();
    const device = searchParams.get('device') || '';

    return (
        <Container maxWidth="md" sx={{ py: 4 }}>
            <PeopleSection device={device} />
            <Divider sx={{ my: 4 }} />
            <LocationsSection />
            <Divider sx={{ my: 4 }} />
            <MealTimesSection device={device} />
            <Divider sx={{ my: 4 }} />
            <DevicesSection />
        </Container>
    );
};

export default Profile;

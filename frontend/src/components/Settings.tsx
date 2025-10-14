import { useEffect, useState } from 'react';
import { getSettingsRequest, toogleModeRequest } from '../apis/controls';
import useSWR from 'swr';
import { Stack, Switch, Typography } from '@mui/material';
import { PhotoOutlined, VideocamOutlined } from '@mui/icons-material';

const Settings = () => {
    const [isVideoMode, setIsVideoMode] = useState(false);
    const { data, mutate } = useSWR('settings', getSettingsRequest, {
        revalidateOnFocus: false,
    });

    useEffect(() => {
        if (data) {
            setIsVideoMode(data.captureMode === 'video');
        }
    }, [data]);

    useEffect(() => {
        toogleModeRequest(isVideoMode ? 'video' : 'photo')
            .then(() => {
                mutate();
            })
            .catch((error) => {
                console.error('There was an error toggling mode!', error);
            });
    }, [isVideoMode]);

    if (!data) {
        return null;
    }

    return (
        <Stack spacing={2} alignItems="center" marginTop={4}>
            <Typography>Capturing Mode:</Typography>
            <Stack direction="row" spacing={1} alignItems="center">
                <PhotoOutlined color={isVideoMode ? 'action' : 'primary'} />
                <Switch
                    checked={isVideoMode}
                    onChange={(e) => {
                        const newMode = e.target.checked ? 'video' : 'photo';
                        setIsVideoMode(e.target.checked);
                        if (newMode === 'video') {
                            // switch back to photo mode after 5 minutes
                            setTimeout(() => {
                                setIsVideoMode(false);
                            }, 1000 * (data.videoSettings.maxDuration || 30));
                        }
                    }}
                />
                <VideocamOutlined color={!isVideoMode ? 'action' : 'primary'} />
            </Stack>
        </Stack>
    );
};

export default Settings;

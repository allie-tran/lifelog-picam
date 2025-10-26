import { Box, Button, Stack, Tooltip, Typography } from '@mui/material';
import { SummarySegment } from '@utils/types';
import { getDaySummary, processDate } from 'apis/process';
import CATEGORIES from 'constants/activityColors';
import { useSearchParams } from 'react-router';
import useSWR from 'swr';
import 'utils/animation.css';

const DaySummary = () => {
    const [searchParams, _] = useSearchParams();
    const date = searchParams.get('date');

    const { data: daySummary } = useSWR(
        date ? `day-summary-${date}` : null,
        () => (date ? getDaySummary(date) : null),
        {
            revalidateOnFocus: false,
        }
    );

    return (
        <Stack spacing={2} alignItems="center" padding={2}>
            <Typography variant="h6" fontWeight="bold">
                Day Summary
            </Typography>
            <Button
                variant="contained"
                onClick={() =>
                    processDate(date || '').then(() => {
                        alert(
                            'The day is being processed. Please refresh later.'
                        );
                    })
                }
            >
                Process Activities for This Day
            </Button>
            {daySummary && (
                <Typography
                    variant="body1"
                    textAlign="center"
                    sx={{ maxWidth: 600 }}
                >
                    {daySummary.summaryText ||
                        'No summary available for this day.'}
                </Typography>
            )}
            {daySummary && (
                <Stack
                    direction="row"
                    spacing={0}
                    sx={{
                        overflowX: 'auto',
                        width: '100%',
                        border: '1px solid #ccc',
                        padding: 1,
                    }}
                    flexWrap="wrap"
                >
                    {daySummary.segments.map(
                        (segment: SummarySegment, index: number) => (
                            <Tooltip
                                title={`${segment.activity}: ${segment.startTime} - ${segment.endTime}`}
                                key={index}
                            >
                                <Box
                                    sx={{
                                        height: 48,
                                        width: 10,
                                        backgroundColor:
                                            CATEGORIES[segment.activity] ||
                                            '#bdc3c7',
                                    }}
                                    key={index}
                                ></Box>
                            </Tooltip>
                        )
                    )}
                </Stack>
            )}
        </Stack>
    );
};

export default DaySummary;

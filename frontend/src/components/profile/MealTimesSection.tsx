import { AutorenewRounded, RestaurantRounded } from '@mui/icons-material';
import {
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    CircularProgress,
    FormControlLabel,
    Stack,
    Switch,
    TextField,
    Typography,
} from '@mui/material';
import React from 'react';
import useSWR from 'swr';
import {
    MealKind,
    MealTime,
    deleteMealTime,
    getMealTimes,
    putMealTime,
    relearnMealTimes,
} from 'apis/profile';

const MEALS: MealKind[] = ['breakfast', 'lunch', 'dinner'];

const minuteToHHMM = (m: number): string => {
    const hh = Math.floor(m / 60)
        .toString()
        .padStart(2, '0');
    const mm = (m % 60).toString().padStart(2, '0');
    return `${hh}:${mm}`;
};

const hhmmToMinute = (s: string): number => {
    const [hh, mm] = s.split(':').map((x) => parseInt(x, 10));
    return (hh || 0) * 60 + (mm || 0);
};

const MealCard = ({
    device,
    meal,
    existing,
    onChanged,
}: {
    device: string;
    meal: MealKind;
    existing?: MealTime;
    onChanged: () => void;
}) => {
    const [enabled, setEnabled] = React.useState(existing?.enabled ?? false);
    const [time, setTime] = React.useState(
        minuteToHHMM(existing?.usualMinute ?? (meal === 'breakfast' ? 480 : meal === 'lunch' ? 750 : 1140)),
    );
    const [grace, setGrace] = React.useState(existing?.graceMinute ?? 90);
    const [busy, setBusy] = React.useState(false);

    React.useEffect(() => {
        if (existing) {
            setEnabled(existing.enabled);
            setTime(minuteToHHMM(existing.usualMinute));
            setGrace(existing.graceMinute);
        }
    }, [existing]);

    const handleSave = async () => {
        setBusy(true);
        try {
            await putMealTime(device, {
                meal,
                usualMinute: hhmmToMinute(time),
                graceMinute: grace,
                enabled,
            });
            onChanged();
        } finally {
            setBusy(false);
        }
    };

    const handleReset = async () => {
        setBusy(true);
        try {
            await deleteMealTime(device, meal);
            onChanged();
        } finally {
            setBusy(false);
        }
    };

    return (
        <Card variant="outlined" sx={{ width: { xs: '100%', sm: 280 } }}>
            <CardContent>
                <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
                    <Typography variant="subtitle1" fontWeight={700} textTransform="capitalize">
                        {meal}
                    </Typography>
                    {existing && (
                        <Chip
                            size="small"
                            variant="outlined"
                            label={existing.auto ? 'auto-learned' : 'manual'}
                            color={existing.auto ? 'default' : 'primary'}
                        />
                    )}
                </Stack>

                <Stack spacing={1.5}>
                    <TextField
                        label="Usual time"
                        type="time"
                        size="small"
                        value={time}
                        onChange={(e) => setTime(e.target.value)}
                        InputLabelProps={{ shrink: true }}
                        fullWidth
                    />
                    <TextField
                        label="Remind after (minutes late)"
                        type="number"
                        size="small"
                        value={grace}
                        onChange={(e) => setGrace(Math.max(0, parseInt(e.target.value, 10) || 0))}
                        fullWidth
                    />
                    <FormControlLabel
                        control={<Switch checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />}
                        label="Remind me if I miss it"
                    />
                    <Stack direction="row" spacing={1}>
                        <Button variant="contained" size="small" disabled={busy} onClick={handleSave}>
                            {busy ? <CircularProgress size={16} /> : 'Save'}
                        </Button>
                        {existing && (
                            <Button size="small" color="inherit" disabled={busy} onClick={handleReset}>
                                Reset
                            </Button>
                        )}
                    </Stack>
                </Stack>
            </CardContent>
        </Card>
    );
};

const MealTimesSection = ({ device }: { device: string }) => {
    const { data, mutate, isLoading } = useSWR(
        device ? ['meal-times', device] : null,
        () => getMealTimes(device),
        { revalidateOnFocus: false },
    );
    const [relearning, setRelearning] = React.useState(false);

    const byMeal = React.useMemo(() => {
        const m: Partial<Record<MealKind, MealTime>> = {};
        (data ?? []).forEach((t) => {
            m[t.meal] = t;
        });
        return m;
    }, [data]);

    const handleRelearn = async () => {
        setRelearning(true);
        try {
            await relearnMealTimes(device);
            mutate();
        } finally {
            setRelearning(false);
        }
    };

    return (
        <Box>
            <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
                <RestaurantRounded color="primary" />
                <Typography variant="h6" color="primary">
                    Meal Times
                </Typography>
            </Stack>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                Set your usual meal times to get a reminder when you haven&apos;t eaten on time.
                Times are auto-learned from your history; edit any to override.
            </Typography>

            <Button
                size="small"
                startIcon={relearning ? <CircularProgress size={14} /> : <AutorenewRounded />}
                disabled={relearning || !device}
                onClick={handleRelearn}
                sx={{ mb: 2 }}
            >
                Re-learn from history
            </Button>

            {isLoading && <CircularProgress size={20} />}

            <Stack direction="row" flexWrap="wrap" spacing={2} useFlexGap>
                {MEALS.map((meal) => (
                    <MealCard
                        key={meal}
                        device={device}
                        meal={meal}
                        existing={byMeal[meal]}
                        onChanged={() => mutate()}
                    />
                ))}
            </Stack>
        </Box>
    );
};

export default MealTimesSection;

import { AddRounded, DeleteRounded } from '@mui/icons-material';
import {
    Button,
    FormControl,
    IconButton,
    InputLabel,
    List,
    ListItem,
    ListItemText,
    MenuItem,
    Select,
    Stack,
    TextField,
    Typography
} from '@mui/material';
import { getUserGoals } from 'apis/browsing';
import { CATEGORIES } from 'constants/activityColors';
import { useEffect, useState } from 'react';
import { useAppSelector } from 'reducers/hooks';
import useSWR from 'swr';
import { ActionType, CustomGoal } from 'utils/types';

const GoalConfig = ({ onSave }: { onSave: (goals: CustomGoal[]) => void }) => {
    const deviceId = useAppSelector((state) => state.auth.deviceId) || '';
    const [goals, setGoals] = useState<CustomGoal[]>([]);
    const [newName, setNewName] = useState('');
    const [newType, setNewType] = useState<ActionType>(ActionType.BINARY);
    const [detail, setDetail] = useState('');
    const { data, isLoading } = useSWR(
        'get-targets',
        () => getUserGoals(deviceId),
        {
            revalidateOnFocus: false,
            shouldRetryOnError: false,
        }
    );

    useEffect(() => {
        if (data) {
            setGoals(data);
        }
    }, [data]);

    const addGoal = () => {
        if (!newName) return;
        setGoals([
            ...goals,
            { name: newName, type: newType, query_prompt: detail },
        ]);
        setNewName('');
    };

    const removeGoal = (index: number) => {
        setGoals(goals.filter((_, i) => i !== index));
    };

    return (
        <Stack spacing={2}>
            <Typography variant="subtitle1" fontWeight="bold" gutterBottom>
                Configure Custom Tracking Goals
            </Typography>

            <Stack direction="row" spacing={2}>
                {newType === ActionType.PERIOD ? (
                    <Select
                        value={newName}
                        onChange={(e) => {
                            console.log(e.target.value);
                            setNewName(e.target.value as string);
                        }}
                        size="small"
                        sx={{ minWidth: 200 }}
                    >
                        {Object.keys(CATEGORIES).map((category) => (
                            <MenuItem key={category} value={category}>
                                {category}
                            </MenuItem>
                        ))}
                    </Select>
                ) : (
                    <TextField
                        size="small"
                        label="Goal Name (e.g., 'Drinking Water')"
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        sx={{ minWidth: 200 }}
                    />
                )}
                <FormControl size="small" sx={{ minWidth: 120 }}>
                    <InputLabel>Type</InputLabel>
                    <Select
                        value={newType}
                        label="Type"
                        onChange={(e) =>
                            setNewType(e.target.value as ActionType)
                        }
                        sx={{ width: 200 }}
                    >
                        <MenuItem value={ActionType.BURST}>
                            Burst (Count)
                        </MenuItem>
                        <MenuItem value={ActionType.PERIOD}>
                            Period (Segments)
                        </MenuItem>
                        <MenuItem value={ActionType.BINARY}>
                            Binary (Duration)
                        </MenuItem>
                    </Select>
                </FormControl>
                <Button
                    variant="contained"
                    onClick={addGoal}
                    startIcon={<AddRounded />}
                >
                    Add
                </Button>
            </Stack>
            {newType !== ActionType.PERIOD ? (
                <TextField
                    size="small"
                    label="Goal Description"
                    value={detail}
                    placeholder={'A photo of <detail> would work well here'}
                    onChange={(e) => setDetail(e.target.value)}
                />
            ) : null}
            <List dense>
                {goals.map((goal, index) => (
                    <ListItem
                        key={index}
                        secondaryAction={
                            <IconButton
                                edge="end"
                                onClick={() => removeGoal(index)}
                            >
                                <DeleteRounded />
                            </IconButton>
                        }
                    >
                        <ListItemText
                            primary={goal.name}
                            secondary={`Type: ${goal.type}`}
                        />
                    </ListItem>
                ))}
            </List>
            <Button
                fullWidth
                variant="outlined"
                color="primary"
                onClick={() => onSave(goals)}
                disabled={goals.length === 0}
            >
                Apply Goals to Summary
            </Button>
        </Stack>
    );
};

export default GoalConfig;

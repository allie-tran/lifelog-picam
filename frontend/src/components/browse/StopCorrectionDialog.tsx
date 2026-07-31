import {
    Alert,
    Box,
    Button,
    CircularProgress,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    FormControlLabel,
    Radio,
    RadioGroup,
    Stack,
    TextField,
    Typography,
} from '@mui/material';
import { useEffect, useState } from 'react';
import {
    correctStop,
    getStopCandidates,
    StopVenueCandidate,
} from 'apis/location';

interface Props {
    open: boolean;
    device: string;
    date: string;
    segmentIds: number[];
    currentName?: string | null;
    onClose: () => void;
    onCorrected?: () => void;
}

const CUSTOM = '__custom__';

export default function StopCorrectionDialog({
    open,
    device,
    date,
    segmentIds,
    currentName,
    onClose,
    onCorrected,
}: Props) {
    const [candidates, setCandidates] = useState<StopVenueCandidate[]>([]);
    const [loading, setLoading] = useState(false);
    const [selected, setSelected] = useState<string>('');
    const [customName, setCustomName] = useState('');
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (!open) return;
        setError(null);
        setSelected('');
        setCustomName('');
        setLoading(true);
        getStopCandidates(device, date, segmentIds)
            .then((c) => {
                setCandidates(c);
                // Preselect the current venue if present.
                const curIdx = c.findIndex((x) => x.isCurrent);
                setSelected(curIdx >= 0 ? String(curIdx) : '');
            })
            .catch(() => setError('Could not load nearby venues.'))
            .finally(() => setLoading(false));
    }, [open, device, date, segmentIds]);

    const handleSave = async () => {
        setError(null);
        let name = '';
        let osmType: string | null = null;
        let osmId: string | null = null;
        if (selected === CUSTOM) {
            name = customName.trim();
            if (!name) {
                setError('Type a venue name.');
                return;
            }
        } else if (selected !== '') {
            const c = candidates[Number(selected)];
            if (!c) return;
            name = c.name;
            osmType = c.osmType ?? null;
            osmId = c.osmId ?? null;
        } else {
            setError('Pick a venue or type a name.');
            return;
        }
        setSaving(true);
        try {
            await correctStop({ device, date, segmentIds, name, osmType, osmId });
            onCorrected?.();
            onClose();
        } catch (e: any) {
            setError(e?.response?.data?.detail || 'Correction failed.');
        } finally {
            setSaving(false);
        }
    };

    return (
        <Dialog open={open} onClose={saving ? undefined : onClose} maxWidth="xs" fullWidth>
            <DialogTitle>Correct location</DialogTitle>
            <DialogContent dividers>
                <Typography variant="caption" color="text.secondary">
                    Applies to this stop only — other visits to the same place are left
                    unchanged.
                </Typography>
                {loading ? (
                    <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
                        <CircularProgress size={24} />
                    </Box>
                ) : (
                    <RadioGroup value={selected} onChange={(e) => setSelected(e.target.value)}>
                        <Stack sx={{ mt: 1 }}>
                            {candidates.map((c, i) => (
                                <FormControlLabel
                                    key={`${c.osmType ?? 'x'}-${c.osmId ?? i}`}
                                    value={String(i)}
                                    control={<Radio size="small" />}
                                    label={
                                        <Box>
                                            <Typography variant="body2" component="span">
                                                {c.name}
                                                {c.isCurrent && (
                                                    <Typography
                                                        variant="caption"
                                                        color="text.secondary"
                                                        component="span"
                                                        sx={{ ml: 0.5 }}
                                                    >
                                                        (current)
                                                    </Typography>
                                                )}
                                            </Typography>
                                            {c.distanceM != null && !c.isCurrent && (
                                                <Typography
                                                    variant="caption"
                                                    color="text.secondary"
                                                    sx={{ ml: 0.5 }}
                                                >
                                                    {Math.round(c.distanceM)}m
                                                    {c.category ? ` · ${c.category}` : ''}
                                                </Typography>
                                            )}
                                        </Box>
                                    }
                                />
                            ))}
                            <FormControlLabel
                                value={CUSTOM}
                                control={<Radio size="small" />}
                                label={
                                    <TextField
                                        placeholder="Type a name…"
                                        variant="standard"
                                        size="small"
                                        value={customName}
                                        onChange={(e) => setCustomName(e.target.value)}
                                        onFocus={() => setSelected(CUSTOM)}
                                        sx={{ minWidth: 200 }}
                                    />
                                }
                            />
                        </Stack>
                    </RadioGroup>
                )}
                {error && (
                    <Alert severity="error" sx={{ mt: 1 }}>
                        {error}
                    </Alert>
                )}
            </DialogContent>
            <DialogActions>
                <Button onClick={onClose} disabled={saving}>
                    Cancel
                </Button>
                <Button onClick={handleSave} variant="contained" disabled={saving || loading}>
                    {saving ? 'Saving…' : 'Save'}
                </Button>
            </DialogActions>
        </Dialog>
    );
}

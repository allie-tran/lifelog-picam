import {
    CalendarTodayRounded,
    EventRounded,
    LocalActivityRounded,
    PersonRounded,
    PlaceRounded,
    PublicRounded,
} from '@mui/icons-material';
import { Box, Chip, Collapse, Skeleton, Stack, Typography } from '@mui/material';
import { CountItem, LocationSummaryItem } from 'apis/browsing';
import { getAllFaces } from '@apis/searchFilters';
import React, { useState } from 'react';
import { useSearchParams } from 'react-router';
import useSWR from 'swr';

const SummaryRow = ({
    icon,
    children,
}: {
    icon: React.ReactNode;
    children: React.ReactNode;
}) => (
    <Stack direction="row" alignItems="center" spacing={1}>
        <Box
            sx={{
                mt: '3px',
                color: 'text.secondary',
                display: 'flex',
                alignItems: 'center',
                flexShrink: 0,
            }}
        >
            {icon}
        </Box>
        <Box sx={{ flex: 1 }}>{children}</Box>
    </Stack>
);

// Caps a chip row to `max` items; the rest expand/collapse with a smooth height
// transition so the summary doesn't dump a wall of chips or jump on toggle.
const ExpandableRow = ({
    nodes,
    max,
    spacing = 0.5,
}: {
    nodes: React.ReactNode[];
    max: number;
    spacing?: number;
}) => {
    const [open, setOpen] = useState(false);
    const visible = nodes.slice(0, max);
    const rest = nodes.slice(max);

    return (
        <Box>
            <Stack direction="row" spacing={spacing} flexWrap="wrap" useFlexGap>
                {visible}
                {rest.length > 0 && (
                    <Chip
                        size="small"
                        variant="outlined"
                        label={open ? 'Show less' : `+${rest.length} more`}
                        onClick={() => setOpen((o) => !o)}
                        sx={{ fontSize: '11px', cursor: 'pointer' }}
                    />
                )}
            </Stack>
            <Collapse in={open} timeout={200} unmountOnExit>
                <Stack
                    direction="row"
                    spacing={spacing}
                    flexWrap="wrap"
                    useFlexGap
                    sx={{ mt: spacing }}
                >
                    {rest}
                </Stack>
            </Collapse>
        </Box>
    );
};

const MAX_CHIPS = 6;

const LocationChip = ({
    location,
    onClick,
    onHighlight,
}: {
    location: LocationSummaryItem;
    onClick: () => void;
    onHighlight?: (id: string | null) => void;
}) => {
    const [hovered, setHovered] = useState(false);

    return (
        <Chip
            size="small"
            label={`${location.name} (${location.count})`}
            onClick={onClick}
            onMouseEnter={() => { setHovered(true); if (location.id) onHighlight?.(location.id); }}
            onMouseLeave={() => { setHovered(false); onHighlight?.(null); }}
            sx={{
                cursor: 'pointer',
                fontSize: '11px',
                transition: 'all 0.15s',
                ...(hovered && {
                    backgroundColor: 'primary.main',
                    color: 'primary.contrastText',
                    '& .MuiChip-label': { color: 'inherit' },
                    transform: 'scale(1.06)',
                    boxShadow: 3,
                }),
            }}
        />
    );
};

const ChipSkeleton = ({ width }: { width: number }) => (
    <Skeleton variant="rounded" width={width} height={20} sx={{ borderRadius: '12px' }} />
);

// Mirrors ResultSummaryBar's row structure (same container + SummaryRows) so the
// real bar swaps in without layout shift.
export const ResultSummaryBarSkeleton = () => (
    <Stack
        spacing={0.75}
        sx={{ p: 1, border: 1, borderColor: 'divider', borderRadius: 1, width: '100%' }}
    >
        <SummaryRow icon={<CalendarTodayRounded sx={{ fontSize: 15 }} />}>
            <Skeleton variant="text" width={150} />
        </SummaryRow>
        <SummaryRow icon={<EventRounded sx={{ fontSize: 15 }} />}>
            <Skeleton variant="text" width={200} />
        </SummaryRow>
        <SummaryRow icon={<LocalActivityRounded sx={{ fontSize: 15 }} />}>
            <Stack direction="row" spacing={0.5}>
                {[64, 80, 56].map((w, i) => <ChipSkeleton key={i} width={w} />)}
            </Stack>
        </SummaryRow>
        <SummaryRow icon={<PlaceRounded sx={{ fontSize: 15 }} />}>
            <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                {[90, 70, 110, 80].map((w, i) => <ChipSkeleton key={i} width={w} />)}
            </Stack>
        </SummaryRow>
        <SummaryRow icon={<PersonRounded sx={{ fontSize: 15 }} />}>
            <Stack direction="row" spacing={1}>
                {[0, 1, 2].map((i) => (
                    <Stack key={i} alignItems="center" spacing={0.25}>
                        <Skeleton variant="circular" width={36} height={36} />
                        <Skeleton variant="text" width={40} />
                    </Stack>
                ))}
            </Stack>
        </SummaryRow>
    </Stack>
);

export type ResultSummaryBarProps = {
    dateRange: string;
    eventCount: number;
    photoCount: number;
    topActivities: string[];
    topLocations: LocationSummaryItem[];
    topCountries: CountItem[];
    topPeople: CountItem[];
    onAppendToQuery: (text: string) => void;
    onAddLocationFilter?: (id: string, name: string) => void;
    onAddPersonFilter?: (id: string) => void;
    onHighlightLocation?: (id: string | null) => void;
};

const ResultSummaryBar = ({
    dateRange,
    eventCount,
    photoCount,
    topActivities,
    topLocations,
    topCountries,
    topPeople,
    onAppendToQuery,
    onAddLocationFilter,
    onAddPersonFilter,
    onHighlightLocation,
}: ResultSummaryBarProps) => {
    const [searchParams] = useSearchParams();
    const device = searchParams.get('device') || '';
    const { data: availableFaces } = useSWR(
        device ? [device, 'faces'] : null,
        () => getAllFaces(device),
        { revalidateOnFocus: false, revalidateOnReconnect: false }
    );

    const facesByName = React.useMemo(() => {
        const map: Record<string, { images: string[]; id: string }> = {};
        for (const face of availableFaces ?? []) {
            map[face.name] = { images: face.images, id: face.id };
        }
        return map;
    }, [availableFaces]);

    return (
        <Stack spacing={0.75} sx={{ p: 1, border: 1, borderColor: 'divider', borderRadius: 1 }}>
            <SummaryRow icon={<CalendarTodayRounded sx={{ fontSize: 15 }} />}>
                <Typography variant="body2">{dateRange}</Typography>
            </SummaryRow>

            <SummaryRow icon={<EventRounded sx={{ fontSize: 15 }} />}>
                <Typography variant="body2">
                    {eventCount.toLocaleString()} events ·{' '}
                    {photoCount.toLocaleString()} photos
                </Typography>
            </SummaryRow>

            {topActivities.length > 0 && (
                <SummaryRow
                    icon={<LocalActivityRounded sx={{ fontSize: 15 }} />}
                >
                    <Stack
                        direction="row"
                        spacing={0.5}
                        flexWrap="wrap"
                        useFlexGap
                    >
                        {topActivities.map((a) => (
                            <Chip
                                key={a}
                                size="small"
                                label={a}
                                sx={{ fontSize: '11px' }}
                            />
                        ))}
                    </Stack>
                </SummaryRow>
            )}

            {topLocations.length > 0 && (
                <SummaryRow icon={<PlaceRounded sx={{ fontSize: 15 }} />}>
                    <ExpandableRow
                        max={MAX_CHIPS}
                        nodes={topLocations.map((loc) => (
                            <LocationChip
                                key={loc.id ?? loc.name}
                                location={loc}
                                onClick={() => {
                                    if (loc.id)
                                        onAddLocationFilter?.(loc.id, loc.name);
                                    else onAppendToQuery(loc.name);
                                }}
                                onHighlight={onHighlightLocation}
                            />
                        ))}
                    />
                </SummaryRow>
            )}

            {topCountries.length > 0 && (
                <SummaryRow icon={<PublicRounded sx={{ fontSize: 15 }} />}>
                    <ExpandableRow
                        max={MAX_CHIPS}
                        nodes={topCountries.map((c) => (
                            <Chip
                                key={c.name}
                                size="small"
                                label={`${c.name} (${c.count})`}
                                onClick={() => onAppendToQuery(c.name)}
                                sx={{ cursor: 'pointer', fontSize: '11px' }}
                            />
                        ))}
                    />
                </SummaryRow>
            )}

            {topPeople.length > 0 && (
                <SummaryRow icon={<PersonRounded sx={{ fontSize: 15 }} />}>
                    <ExpandableRow
                        max={MAX_CHIPS}
                        spacing={1}
                        nodes={topPeople.map((person) => {
                            const face = facesByName[person.name];
                            return (
                                <Stack
                                    key={person.name}
                                    alignItems="center"
                                    spacing={0.25}
                                    sx={{ cursor: 'pointer' }}
                                    onClick={() => {
                                        const faceId =
                                            facesByName[person.name]?.id;
                                        if (faceId) onAddPersonFilter?.(faceId);
                                    }}
                                    title={`${person.name} — ${person.count} photos`}
                                >
                                    {face?.images[0] ? (
                                        <Box
                                            component="img"
                                            src={face.images[0]}
                                            alt={person.name}
                                            sx={{
                                                width: 36,
                                                height: 36,
                                                borderRadius: '50%',
                                                objectFit: 'cover',
                                                border: '2px solid',
                                                borderColor: 'primary.light',
                                                '&:hover': {
                                                    borderColor: 'primary.main',
                                                    transform: 'scale(1.1)',
                                                },
                                                transition: 'all 0.15s',
                                            }}
                                        />
                                    ) : (
                                        <Box
                                            sx={{
                                                width: 36,
                                                height: 36,
                                                borderRadius: '50%',
                                                backgroundColor: 'grey.300',
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'center',
                                            }}
                                        >
                                            <PersonRounded
                                                sx={{
                                                    fontSize: 20,
                                                    color: 'grey.600',
                                                }}
                                            />
                                        </Box>
                                    )}
                                    <Typography
                                        variant="caption"
                                        sx={{
                                            fontSize: '10px',
                                            maxWidth: 130,
                                            textAlign: 'center',
                                            overflow: 'hidden',
                                            textOverflow: 'ellipsis',
                                            whiteSpace: 'nowrap',
                                        }}
                                    >
                                        {person.name}
                                    </Typography>
                                </Stack>
                            );
                        })}
                    />
                </SummaryRow>
            )}
        </Stack>
    );
};

export default ResultSummaryBar;

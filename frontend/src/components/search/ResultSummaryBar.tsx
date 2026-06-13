import {
    CalendarTodayRounded,
    EventRounded,
    LocalActivityRounded,
    PersonRounded,
    PlaceRounded,
    PublicRounded,
} from '@mui/icons-material';
import { Box, Chip, Stack, Typography } from '@mui/material';
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
                    <Stack
                        direction="row"
                        spacing={0.5}
                        flexWrap="wrap"
                        useFlexGap
                    >
                        {topLocations.map((loc) => (
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
                    </Stack>
                </SummaryRow>
            )}

            {topCountries.length > 0 && (
                <SummaryRow icon={<PublicRounded sx={{ fontSize: 15 }} />}>
                    <Stack
                        direction="row"
                        spacing={0.5}
                        flexWrap="wrap"
                        useFlexGap
                    >
                        {topCountries.map((c) => (
                            <Chip
                                key={c.name}
                                size="small"
                                label={`${c.name} (${c.count})`}
                                onClick={() => onAppendToQuery(c.name)}
                                sx={{ cursor: 'pointer', fontSize: '11px' }}
                            />
                        ))}
                    </Stack>
                </SummaryRow>
            )}

            {topPeople.length > 0 && (
                <SummaryRow icon={<PersonRounded sx={{ fontSize: 15 }} />}>
                    <Stack
                        direction="row"
                        spacing={1}
                        flexWrap="wrap"
                        useFlexGap
                    >
                        {topPeople.map((person) => {
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
                    </Stack>
                </SummaryRow>
            )}
        </Stack>
    );
};

export default ResultSummaryBar;

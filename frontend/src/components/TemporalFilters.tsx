import { getAvailableValues } from '@apis/searchFilters';
import { DeleteRounded } from '@mui/icons-material';
import {
    Box,
    Button,
    Chip,
    IconButton,
    Stack,
    TextField,
    Typography,
} from '@mui/material';
import { applyQueryToParams, parseSearchParams } from '@utils/searchParams';
import dayjs from 'dayjs';
import timezone from 'dayjs/plugin/timezone';
import utc from 'dayjs/plugin/utc';
import { useCallback, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';
import useSWR from 'swr';
import {
    DayOfWeek,
    Month,
    TimeOfDay,
} from 'types/filters';
import { ImageObject } from 'utils/types';
import { THUMBNAIL_HOST_URL } from '../constants/urls';
import TimeHeatmap from './TimeHeatmap';

dayjs.extend(utc);
dayjs.extend(timezone);

const DATE_FORMATS = ['D MMM YYYY', 'D MMMM YYYY', 'YYYY-MM-DD', 'DD/MM/YYYY', 'D/M/YYYY'];

const parseDate = (text: string) => {
    for (const fmt of DATE_FORMATS) {
        const d = dayjs(text.trim(), fmt, true);
        if (d.isValid()) return d;
    }
    const d = dayjs(text.trim());
    return d.isValid() ? d : null;
};

const TemporalFiltersHook = ({
    resultImages = [],
    onDeleteImage,
    onZoomImage,
}: {
    resultImages?: ImageObject[];
    onDeleteImage?: (path: string) => void;
    onZoomImage?: (path: string, isVideo: boolean) => void;
} = {}) => {
    const [searchParams, setSearchParams] = useSearchParams();
    const device = searchParams.get('device') || '';
    const [currentYear, setCurrentYear] = useState<number>(new Date().getFullYear());
    const [startText, setStartText] = useState('');
    const [endText, setEndText] = useState('');

    const { timeOfDays, dayOfWeeks, seasons, months, years, customRanges } =
        parseSearchParams(searchParams);

    const update = useCallback(
        (partial: Parameters<typeof applyQueryToParams>[0]) => {
            setSearchParams((prev) =>
                applyQueryToParams(partial, new URLSearchParams(prev))
            );
        },
        [setSearchParams]
    );

    const { data: availableYears } = useSWR(
        device ? [device, 'year'] : null,
        async () => {
            const raw = await getAvailableValues(device, 'year');
            const parsed = raw.map((y) => parseInt(y));
            setCurrentYear(parsed.length > 0 ? parsed[0] : new Date().getFullYear());
            return parsed;
        }
    );

    const nothingIsSelected =
        timeOfDays.length === 0 &&
        dayOfWeeks.length === 0 &&
        seasons.length === 0 &&
        months.length === 0 &&
        years.length === 0 &&
        customRanges.length === 0;

    // ── date range picker ─────────────────────────────────────────────────

    const handleAddRange = useCallback(() => {
        const start = parseDate(startText);
        if (!start) return;
        const end = endText.trim() ? (parseDate(endText) ?? start) : start;
        const startStr = start.format('YYYY-MM-DD');
        const endStr = end.format('YYYY-MM-DD');
        setSearchParams((prev) => {
            const current = parseSearchParams(new URLSearchParams(prev)).customRanges;
            if (current.some((r) => r.start === startStr && r.end === endStr)) return prev;
            return applyQueryToParams(
                { customRanges: [...current, { start: startStr, end: endStr }] },
                new URLSearchParams(prev)
            );
        });
        setStartText('');
        setEndText('');
    }, [startText, endText, setSearchParams]);

    // ── renders ───────────────────────────────────────────────────────────

    /**
     * Rendered inside the sidebar Temporal Filter accordion.
     * Only year filter chips + date range input — time/day/month are now
     * handled directly by the heatmap below the results.
     */
    const renderFilterOptions = () => (
        <Stack spacing={1.5} sx={{ pt: 0.5, pb: 1 }}>
            {/* Year filter */}
            {availableYears && availableYears.length > 0 && (
                <Box>
                    <Typography variant="caption" color="text.secondary" sx={{ px: 0.5 }}>
                        Year
                    </Typography>
                    <Stack direction="row" flexWrap="wrap" gap={0.5} mt={0.5}>
                        {availableYears.map((yr) => (
                            <Chip
                                key={yr}
                                label={yr}
                                size="small"
                                variant={years.includes(yr) ? 'filled' : 'outlined'}
                                color={years.includes(yr) ? 'primary' : 'default'}
                                onClick={() => {
                                    const next = years.includes(yr)
                                        ? years.filter((y) => y !== yr)
                                        : [...years, yr];
                                    update({ years: next });
                                    setCurrentYear(yr);
                                }}
                            />
                        ))}
                    </Stack>
                </Box>
            )}

            {/* Custom date ranges */}
            <Box>
                <Typography variant="caption" color="text.secondary" sx={{ px: 0.5 }}>
                    Specific dates
                </Typography>
                <Stack spacing={0.75} mt={0.5} mb={0.75}>
                    <TextField
                        size="small"
                        label="Date"
                        placeholder="15 Jun 2024"
                        value={startText}
                        onChange={(e) => setStartText(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleAddRange()}
                        error={startText.trim() !== '' && !parseDate(startText)}
                        helperText={
                            startText.trim() !== '' && !parseDate(startText)
                                ? 'Unrecognised date'
                                : undefined
                        }
                    />
                    <TextField
                        size="small"
                        label="End date (optional)"
                        placeholder="20 Jun 2024"
                        value={endText}
                        onChange={(e) => setEndText(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleAddRange()}
                        error={endText.trim() !== '' && !parseDate(endText)}
                        helperText={
                            endText.trim() !== '' && !parseDate(endText)
                                ? 'Unrecognised date'
                                : undefined
                        }
                    />
                    <Button
                        variant="outlined"
                        size="small"
                        disabled={!startText.trim() || !parseDate(startText)}
                        onClick={handleAddRange}
                    >
                        Add
                    </Button>
                </Stack>
                <Stack direction="row" flexWrap="wrap" gap={0.5}>
                    {customRanges
                        .filter((r) => r.start !== r.end)
                        .map((r) => (
                            <Chip
                                key={`${r.start}-${r.end}`}
                                label={`${dayjs(r.start).format('D MMM')} – ${dayjs(r.end).format('D MMM YYYY')}`}
                                size="small"
                                onDelete={() => {
                                    const { start: rs, end: re } = r;
                                    setSearchParams((prev) => {
                                        const current =
                                            parseSearchParams(new URLSearchParams(prev)).customRanges;
                                        return applyQueryToParams(
                                            {
                                                customRanges: current.filter(
                                                    (x) => !(x.start === rs && x.end === re)
                                                ),
                                            },
                                            new URLSearchParams(prev)
                                        );
                                    });
                                }}
                            />
                        ))}
                </Stack>
            </Box>
        </Stack>
    );

    const renderHeatmap = () => (
        <Stack alignItems="stretch" mt={4} sx={{ width: '100%' }}>
            {/* Year navigation chips */}
            {availableYears && availableYears.length > 1 && (
                <Stack direction="row" alignItems="center" spacing={1} mb={1.5}>
                    <Typography variant="caption" color="text.secondary">
                        Viewing:
                    </Typography>
                    {availableYears.map((yr) => (
                        <Chip
                            key={yr}
                            label={yr}
                            size="small"
                            variant={currentYear === yr ? 'filled' : 'outlined'}
                            color={currentYear === yr ? 'secondary' : 'default'}
                            onClick={() => setCurrentYear(yr)}
                        />
                    ))}
                </Stack>
            )}

            <TimeHeatmap
                timeOfDays={timeOfDays}
                dayOfWeeks={dayOfWeeks}
                months={months}
                currentYear={currentYear}
                customRanges={customRanges}
                resultImages={resultImages}
                onTimeOfDaysChange={(v: TimeOfDay[]) => update({ timeOfDays: v })}
                onDayOfWeeksChange={(v: DayOfWeek[]) => update({ dayOfWeeks: v })}
                onMonthsChange={(v: Month[]) => update({ months: v })}
                onCustomRangesChange={(v) => update({ customRanges: v })}
            />

            {/* Single-day pinned dates (from calendar view clicks) */}
            {customRanges.filter((r) => r.start === r.end).length > 0 && (
                <Stack direction="row" flexWrap="wrap" gap={0.5} mt={1}>
                    {customRanges
                        .filter((r) => r.start === r.end)
                        .map((r) => (
                            <Chip
                                key={r.start}
                                label={dayjs(r.start).format('D MMM YYYY')}
                                size="small"
                                onDelete={() => {
                                    const { start: rs } = r;
                                    setSearchParams((prev) => {
                                        const current =
                                            parseSearchParams(new URLSearchParams(prev)).customRanges;
                                        return applyQueryToParams(
                                            {
                                                customRanges: current.filter(
                                                    (x) => !(x.start === rs && x.end === rs)
                                                ),
                                            },
                                            new URLSearchParams(prev)
                                        );
                                    });
                                }}
                            />
                        ))}
                </Stack>
            )}
        </Stack>
    );

    const renderClearButton = () => (
        <Button
            disabled={nothingIsSelected}
            variant="outlined"
            color="primary"
            sx={{ mt: 2 }}
            onClick={() => {
                update({
                    timeOfDays: [],
                    dayOfWeeks: [],
                    seasons: [],
                    months: [],
                    years: [],
                    customRanges: [],
                });
            }}
        >
            Clear Filters
        </Button>
    );

    return {
        renderFilterOptions,
        renderHeatmap,
        renderClearButton,
        nothingIsSelected,
    };
};

const PhotoStrip = ({
    images,
    currentYear,
    device,
    onDeleteImage,
    onZoomImage,
}: {
    images: ImageObject[];
    currentYear: number;
    device: string;
    onDeleteImage?: (path: string) => void;
    onZoomImage?: (path: string, isVideo: boolean) => void;
}) => {
    const [hoveredPath, setHoveredPath] = useState<string | null>(null);
    const [localDeleted, setLocalDeleted] = useState<Set<string>>(new Set());

    const filtered = useMemo(() => {
        return images
            .filter((img) => {
                const year = new Date(img.timestamp).getFullYear();
                return year === currentYear && !localDeleted.has(img.imagePath);
            })
            .sort(
                (a, b) =>
                    new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
            );
    }, [images, currentYear, localDeleted]);

    if (!filtered.length) return null;

    return (
        <Box
            sx={{
                overflowX: 'auto',
                display: 'flex',
                flexDirection: 'row',
                gap: 0.5,
                mt: 1,
                pb: 1,
                width: '100%',
                alignSelf: 'stretch',
                '&::-webkit-scrollbar': { height: 4 },
                '&::-webkit-scrollbar-thumb': {
                    backgroundColor: 'rgba(0,0,0,0.2)',
                    borderRadius: 2,
                },
            }}
        >
            {filtered.map((img) => {
                const thumbUrl = img.thumbnail
                    ? `${THUMBNAIL_HOST_URL}/${device}/${img.thumbnail}`
                    : '';
                const isHovered = hoveredPath === img.imagePath;
                const ts = dayjs.utc(img.timestamp).tz(img.timezone || 'UTC');
                return (
                    <Box
                        key={img.imagePath}
                        sx={{
                            position: 'relative',
                            flexShrink: 0,
                            height: 68,
                            cursor: 'pointer',
                        }}
                        onMouseEnter={() => setHoveredPath(img.imagePath)}
                        onMouseLeave={() => setHoveredPath(null)}
                        onClick={() =>
                            onZoomImage ? onZoomImage(img.imagePath, img.isVideo) : null
                        }
                    >
                        {thumbUrl ? (
                            <Box
                                component="img"
                                src={thumbUrl}
                                sx={{
                                    height: '100%',
                                    width: 'auto',
                                    borderRadius: '4px',
                                    display: 'block',
                                    opacity: isHovered ? 0.7 : 1,
                                    transition: 'opacity 0.15s',
                                }}
                            />
                        ) : (
                            <Box
                                sx={{
                                    height: 68,
                                    width: 50,
                                    borderRadius: '4px',
                                    backgroundColor: 'grey.300',
                                }}
                            />
                        )}
                        {isHovered && (
                            <Box
                                sx={{
                                    position: 'absolute',
                                    bottom: 0,
                                    left: 0,
                                    right: 0,
                                    backgroundColor: 'rgba(0,0,0,0.75)',
                                    borderRadius: '0 0 4px 4px',
                                    px: 0.5,
                                    py: 0.25,
                                    display: 'flex',
                                    flexDirection: 'column',
                                }}
                                onClick={(e) => e.stopPropagation()}
                            >
                                <Typography
                                    sx={{
                                        fontSize: '9px',
                                        color: 'white',
                                        lineHeight: 1.2,
                                        whiteSpace: 'nowrap',
                                    }}
                                >
                                    {ts.format('HH:mm')}
                                </Typography>
                                <Typography
                                    sx={{
                                        fontSize: '8px',
                                        color: 'rgba(255,255,255,0.7)',
                                        lineHeight: 1.2,
                                        whiteSpace: 'nowrap',
                                    }}
                                >
                                    {ts.format('D MMM')}
                                </Typography>
                                <Stack direction="row" spacing={0} sx={{ mt: 0.25 }}>
                                    <IconButton
                                        size="small"
                                        sx={{ p: 0.25, color: 'error.light' }}
                                        onClick={() => {
                                            setLocalDeleted(
                                                (prev) =>
                                                    new Set(Array.from(prev).concat(img.imagePath))
                                            );
                                            onDeleteImage && onDeleteImage(img.imagePath);
                                        }}
                                    >
                                        <DeleteRounded sx={{ fontSize: 12 }} />
                                    </IconButton>
                                </Stack>
                            </Box>
                        )}
                    </Box>
                );
            })}
        </Box>
    );
};

export { PhotoStrip, TemporalFiltersHook };

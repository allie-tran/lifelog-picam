import { getAvailableValues } from '@apis/searchFilters';
import { DeleteRounded } from '@mui/icons-material';
import {
    Box,
    Button,
    Checkbox,
    Chip,
    Grid,
    IconButton,
    Stack,
    Tab,
    Tabs,
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
    Season,
    TimeOfDay,
    dayOfWeekOptions,
    monthOptions,
    seasonOptions,
    timeOfDayOptions,
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
    const [currentYear, setCurrentYear] = useState<number | null>(null);
    const [tabIndex, setTabIndex] = useState(0);
    const [startText, setStartText] = useState('');
    const [endText, setEndText] = useState('');

    const { timeOfDays, dayOfWeeks, seasons, months, years, customRanges, weekCells, monthCells } =
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
            return parsed;
        },
        { revalidateOnFocus: false }
    );

    const nothingIsSelected =
        timeOfDays.length === 0 &&
        dayOfWeeks.length === 0 &&
        seasons.length === 0 &&
        months.length === 0 &&
        years.length === 0 &&
        customRanges.length === 0 &&
        weekCells.length === 0 &&
        monthCells.length === 0;

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

    const renderFilterOptions = () => (
        <Stack direction="row" sx={{ minHeight: 180 }}>
            <Tabs
                value={tabIndex}
                onChange={(_, v) => setTabIndex(v)}
                orientation="vertical"
                sx={{
                    borderRight: 1,
                    borderColor: 'divider',
                    minWidth: 80,
                    '& .MuiTab-root': {
                        minHeight: 32,
                        py: 0.5,
                        px: 1,
                        fontSize: '11px',
                        alignItems: 'flex-start',
                        textAlign: 'left',
                    },
                }}
            >
                <Tab label="Time" />
                <Tab label="Week Day" />
                <Tab label="Season" />
                <Tab label="Month" />
                <Tab label="Year" />
                <Tab label="Date" />
            </Tabs>
            <Box sx={{ flex: 1, pl: 1, overflowY: 'auto', maxHeight: 220 }}>
                {tabIndex === 0 && (
                    <ListOfCheckBoxes
                        options={timeOfDayOptions}
                        selectedOptions={timeOfDays}
                        onChange={(selected) => update({ timeOfDays: selected as TimeOfDay[] })}
                    />
                )}
                {tabIndex === 1 && (
                    <ListOfCheckBoxes
                        options={dayOfWeekOptions}
                        selectedOptions={dayOfWeeks}
                        onChange={(selected) => update({ dayOfWeeks: selected as DayOfWeek[] })}
                    />
                )}
                {tabIndex === 2 && (
                    <ListOfCheckBoxes
                        options={seasonOptions}
                        selectedOptions={seasons}
                        onChange={(selected) => update({ seasons: selected as Season[] })}
                    />
                )}
                {tabIndex === 3 && (
                    <ListOfCheckBoxes
                        options={monthOptions}
                        selectedOptions={months}
                        onChange={(selected) => update({ months: selected as Month[] })}
                    />
                )}
                {tabIndex === 4 && (
                    <ListOfCheckBoxes
                        options={availableYears ? availableYears.map(String) : []}
                        selectedOptions={years.map(String)}
                        onChange={(selected) => {
                            update({ years: selected.map(Number) });
                            if (selected.length > 0)
                                setCurrentYear(Number(selected[selected.length - 1]));
                            else if (availableYears && availableYears.length > 0)
                                setCurrentYear(availableYears[0]);
                        }}
                    />
                )}
                {tabIndex === 5 && (
                    <Box mt={1}>
                        <Stack spacing={0.75} mb={1}>
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
                                disabled={
                                    !startText.trim() ||
                                    !parseDate(startText) ||
                                    (endText.trim() !== '' && !parseDate(endText))
                                }
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
                                                const current = parseSearchParams(
                                                    new URLSearchParams(prev)
                                                ).customRanges;
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
                )}
            </Box>
        </Stack>
    );

    const renderHeatmap = () => (
        <Stack alignItems="stretch" sx={{ width: '100%' }} px={2}>
            {/* Year navigation chips */}
            {availableYears && availableYears.length > 1 && (
                <Stack direction="row" alignItems="center" spacing={1} mb={1.5} flexWrap="wrap">
                    <Typography variant="caption" color="text.secondary">
                        Viewing:
                    </Typography>
                    <Chip
                        label="All"
                        size="small"
                        variant={currentYear === null ? 'filled' : 'outlined'}
                        color={currentYear === null ? 'secondary' : 'default'}
                        onClick={() => setCurrentYear(null)}
                    />
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
                weekCells={weekCells}
                monthCells={monthCells}
                resultImages={resultImages}
                onTimeOfDaysChange={(v: TimeOfDay[]) => update({ timeOfDays: v })}
                onDayOfWeeksChange={(v: DayOfWeek[]) => update({ dayOfWeeks: v })}
                onMonthsChange={(v: Month[]) => update({ months: v })}
                onCustomRangesChange={(v) => update({ customRanges: v })}
                onWeekCellsChange={(v) => update({ weekCells: v })}
                onMonthCellsChange={(v) => update({ monthCells: v })}
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
                    weekCells: [],
                    monthCells: [],
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

const CheckboxWithText = ({
    label,
    checked,
    onChange,
    disabled = false,
}: {
    label: string;
    checked: boolean;
    onChange: (checked: boolean) => void;
    disabled?: boolean;
}) => (
    <Grid size={6} sx={{ overflow: 'hidden', whiteSpace: 'nowrap' }}>
        <Checkbox
            size="small"
            disabled={disabled}
            checked={checked}
            onChange={(e) => onChange(e.target.checked)}
            sx={{ padding: '4px' }}
        />
        <Typography variant="caption" sx={{ display: 'inline-block', ml: -0.5 }}>
            {label.slice(0, 1).toUpperCase() + label.slice(1)}
        </Typography>
    </Grid>
);

const ListOfCheckBoxes = ({
    options,
    selectedOptions,
    onChange,
}: {
    options: string[];
    selectedOptions: string[];
    onChange: (selected: string[]) => void;
}) => (
    <Grid container spacing={1}>
        <CheckboxWithText
            label="All"
            checked={selectedOptions.length === options.length}
            onChange={(checked) => onChange(checked ? options : [])}
        />
        {options.map((option) => (
            <CheckboxWithText
                key={option}
                label={option}
                checked={selectedOptions.includes(option)}
                onChange={(checked) =>
                    onChange(
                        checked
                            ? [...selectedOptions, option]
                            : selectedOptions.filter((o) => o !== option)
                    )
                }
            />
        ))}
        <CheckboxWithText
            label="None"
            disabled={selectedOptions.length === 0}
            checked={false}
            onChange={(checked) => { if (checked) onChange([]); }}
        />
    </Grid>
);

const PhotoStrip = ({
    images,
    currentYear,
    device,
    onDeleteImage,
    onZoomImage,
}: {
    images: ImageObject[];
    currentYear: number | null;
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
                return (currentYear === null || year === currentYear) && !localDeleted.has(img.imagePath);
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

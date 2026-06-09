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
    Typography,
} from '@mui/material';
import { DeleteRounded } from '@mui/icons-material';
import { useMemo, useState } from 'react';
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
import TimeHeatmap from './TimeHeatmap';
import useSWR from 'swr';
import { getAvailableValues } from '@apis/searchFilters';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import { useSearchParams } from 'react-router';
import { setSearchQuery } from 'reducers/search';
import { DatePicker } from '@mui/x-date-pickers/DatePicker';
import dayjs, { Dayjs } from 'dayjs';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';
import { ImageObject } from 'utils/types';
import { THUMBNAIL_HOST_URL } from '../constants/urls';

dayjs.extend(utc);
dayjs.extend(timezone);

const TemporalFiltersHook = ({
    resultImages = [],
    onDeleteImage,
    onZoomImage,
}: {
    resultImages?: ImageObject[];
    onDeleteImage?: (path: string) => void;
    onZoomImage?: (path: string, isVideo: boolean) => void;
} = {}) => {
    const dispatch = useAppDispatch();
    const [searchParams] = useSearchParams();
    const device = searchParams.get('device') || '';
    const [tabIndex, setTabIndex] = useState(0);
    const [currentYear, setCurrentYear] = useState<number>(
        new Date().getFullYear()
    );
    const [customCells, setCustomCells] = useState<
        Set<{ row: number; col: number; value: number }>
    >(new Set());
    const { timeOfDays, dayOfWeeks, seasons, months, years, customRanges } = useAppSelector(
        (state) => state.search.query
    );
    const [pendingDate, setPendingDate] = useState<Dayjs | null>(null);

    const { data: availableYears } = useSWR([device, 'year'], async () => {
        const years = await getAvailableValues(device, 'year');
        setCurrentYear(
            years.length > 0 ? parseInt(years[0]) : new Date().getFullYear()
        );
        return years.map((y) => parseInt(y));
    });

    const { data: availableDates } = useSWR([device, 'date'], () =>
        getAvailableValues(device, 'date')
    );
    const availableDatesSet = useMemo(
        () => new Set(availableDates ?? []),
        [availableDates]
    );

    const nothingIsSelected =
        timeOfDays.length === 0 &&
        dayOfWeeks.length === 0 &&
        seasons.length === 0 &&
        months.length === 0 &&
        years.length === 0 &&
        customRanges.length === 0 &&
        customCells.size === 0;

    const noFiltersSelected =
        timeOfDays.length === 0 &&
        dayOfWeeks.length === 0 &&
        seasons.length === 0 &&
        months.length === 0 &&
        years.length === 0 &&
        customRanges.length === 0;

    const renderFilterOptions = () => (
        <Stack direction="row" sx={{ minHeight: 180 }}>
            <Tabs
                value={tabIndex}
                onChange={(_, newValue) => setTabIndex(newValue)}
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
                        onChange={(selected) =>
                            dispatch(
                                setSearchQuery({
                                    timeOfDays: selected as TimeOfDay[],
                                })
                            )
                        }
                    />
                )}
                {tabIndex === 1 && (
                    <ListOfCheckBoxes
                        options={dayOfWeekOptions}
                        selectedOptions={dayOfWeeks}
                        onChange={(selected) =>
                            dispatch(
                                setSearchQuery({
                                    dayOfWeeks: selected as DayOfWeek[],
                                })
                            )
                        }
                    />
                )}
                {tabIndex === 2 && (
                    <ListOfCheckBoxes
                        options={seasonOptions}
                        selectedOptions={seasons}
                        onChange={(selected) =>
                            dispatch(
                                setSearchQuery({ seasons: selected as Season[] })
                            )
                        }
                    />
                )}
                {tabIndex === 3 && (
                    <ListOfCheckBoxes
                        options={monthOptions}
                        selectedOptions={months}
                        onChange={(selected) =>
                            dispatch(
                                setSearchQuery({ months: selected as Month[] })
                            )
                        }
                    />
                )}
                {tabIndex === 4 && (
                    <ListOfCheckBoxes
                        options={availableYears ? availableYears.map(String) : []}
                        selectedOptions={years.map(String)}
                        onChange={(selected) =>
                            dispatch(setSearchQuery({ years: selected.map(Number) }))
                        }
                    />
                )}
                {tabIndex === 5 && (
                    <Box mt={1}>
                        <Stack spacing={1} alignItems="center" mb={1}>
                            <DatePicker
                                label="Pick a date"
                                value={pendingDate}
                                onChange={(v) => setPendingDate(v)}
                                slotProps={{ textField: { size: 'small' } }}
                                shouldDisableDate={(day) =>
                                    availableDatesSet.size > 0 &&
                                    !availableDatesSet.has(day.format('YYYY-MM-DD'))
                                }
                                referenceDate={
                                    availableDates?.length
                                        ? dayjs(availableDates[availableDates.length - 1])
                                        : dayjs()
                                }
                            />
                            <Button
                                variant="outlined"
                                size="small"
                                disabled={!pendingDate}
                                onClick={() => {
                                    if (!pendingDate) return;
                                    const dateStr = pendingDate.format('YYYY-MM-DD');
                                    const alreadyAdded = customRanges.some(
                                        (r) => r.start === dateStr
                                    );
                                    if (!alreadyAdded) {
                                        dispatch(setSearchQuery({
                                            customRanges: [
                                                ...customRanges,
                                                { start: dateStr, end: dateStr },
                                            ],
                                        }));
                                    }
                                    setPendingDate(null);
                                }}
                            >
                                Add
                            </Button>
                        </Stack>
                        <Stack direction="row" flexWrap="wrap" gap={0.5}>
                            {customRanges.map((r) => (
                                <Chip
                                    key={r.start}
                                    label={dayjs(r.start).format('D MMM YYYY')}
                                    size="small"
                                    onDelete={() =>
                                        dispatch(setSearchQuery({
                                            customRanges: customRanges.filter(
                                                (x) => x.start !== r.start
                                            ),
                                        }))
                                    }
                                />
                            ))}
                        </Stack>
                    </Box>
                )}
            </Box>
        </Stack>
    );

    const renderHeatmap = () => {
        return (
            <Stack alignItems="center" mt={4} sx={{ width: '100%' }}>
                <TimeHeatmap
                    timeOfDays={timeOfDays}
                    dayOfWeeks={dayOfWeeks}
                    seasons={seasons}
                    months={months}
                    years={years}
                    currentYear={currentYear}
                    customCells={customCells}
                    setCustomCells={setCustomCells}
                    nothingIsSelected={nothingIsSelected}
                    noFiltersSelected={noFiltersSelected}
                    resultImages={resultImages}
                />

                <Stack direction="row" alignItems="center" spacing={1} mt={2}>
                    <Typography variant="body2">Year:</Typography>
                    {availableYears?.map((yr) => (
                        <Chip
                            key={yr}
                            label={yr}
                            variant={currentYear === yr ? 'filled' : 'outlined'}
                            size="small"
                            onClick={() => setCurrentYear(yr)}
                        />
                    ))}
                </Stack>
            </Stack>
        );
    };

    const renderClearButton = () => {
        return (
            <Button
                disabled={nothingIsSelected}
                variant="outlined"
                color="primary"
                sx={{ mt: 2 }}
                onClick={() => {
                    dispatch(
                        setSearchQuery({
                            timeOfDays: [],
                            dayOfWeeks: [],
                            seasons: [],
                            months: [],
                            years: [],
                            customRanges: [],
                        })
                    );
                    setCustomCells(new Set());
                }}
            >
                Clear Filters
            </Button>
        );
    };

    return {
        renderFilterOptions,
        renderHeatmap,
        renderClearButton,
        nothingIsSelected,
    };
};

const ListOfCheckBoxes = ({
    options,
    selectedOptions,
    onChange,
}: {
    options: string[];
    selectedOptions: string[];
    onChange: (selected: string[]) => void;
}) => {
    return (
        <Grid container spacing={1}>
            <CheckboxWithText
                label="All"
                checked={selectedOptions.length === options.length}
                onChange={(checked) => {
                    if (checked) {
                        onChange(options);
                    } else {
                        onChange([]);
                    }
                }}
            />
            {options.map((option) => (
                <CheckboxWithText
                    key={option}
                    label={option}
                    checked={selectedOptions.includes(option)}
                    onChange={(checked) => {
                        if (checked) {
                            onChange([...selectedOptions, option]);
                        } else {
                            onChange(
                                selectedOptions.filter((o) => o !== option)
                            );
                        }
                    }}
                />
            ))}
            <CheckboxWithText
                label="None"
                disabled={selectedOptions.length === 0}
                checked={false}
                onChange={(checked) => {
                    if (checked) {
                        onChange([]);
                    }
                }}
            />
        </Grid>
    );
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
            .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
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
                '&::-webkit-scrollbar-thumb': { backgroundColor: 'rgba(0,0,0,0.2)', borderRadius: 2 },
            }}
        >
            {filtered.map((img) => {
                const thumbUrl = img.thumbnail ? `${THUMBNAIL_HOST_URL}/${device}/${img.thumbnail}` : '';
                const isHovered = hoveredPath === img.imagePath;
                const ts = dayjs.utc(img.timestamp).tz(img.timezone || 'UTC');
                return (
                    <Box
                        key={img.imagePath}
                        sx={{ position: 'relative', flexShrink: 0, height: 68, cursor: 'pointer' }}
                        onMouseEnter={() => setHoveredPath(img.imagePath)}
                        onMouseLeave={() => setHoveredPath(null)}
                        onClick={() => onZoomImage ? onZoomImage(img.imagePath, img.isVideo) : null}
                    >
                        {thumbUrl ? (
                            <Box
                                component="img"
                                src={thumbUrl}
                                sx={{ height: '100%', width: 'auto', borderRadius: '4px', display: 'block', opacity: isHovered ? 0.7 : 1, transition: 'opacity 0.15s' }}
                            />
                        ) : (
                            <Box sx={{ height: 68, width: 50, borderRadius: '4px', backgroundColor: 'grey.300' }} />
                        )}
                        {isHovered && (
                            <Box
                                sx={{
                                    position: 'absolute', bottom: 0, left: 0, right: 0,
                                    backgroundColor: 'rgba(0,0,0,0.75)',
                                    borderRadius: '0 0 4px 4px',
                                    px: 0.5, py: 0.25,
                                    display: 'flex', flexDirection: 'column',
                                }}
                                onClick={(e) => e.stopPropagation()}
                            >
                                <Typography sx={{ fontSize: '9px', color: 'white', lineHeight: 1.2, whiteSpace: 'nowrap' }}>
                                    {ts.format('HH:mm')}
                                </Typography>
                                <Typography sx={{ fontSize: '8px', color: 'rgba(255,255,255,0.7)', lineHeight: 1.2, whiteSpace: 'nowrap' }}>
                                    {ts.format('D MMM')}
                                </Typography>
                                <Stack direction="row" spacing={0} sx={{ mt: 0.25 }}>
                                    <IconButton
                                        size="small"
                                        sx={{ p: 0.25, color: 'error.light' }}
                                        onClick={() => {
                                            setLocalDeleted((prev) => new Set(Array.from(prev).concat(img.imagePath)));
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
}) => {
    return (
        <Grid size={6} sx={{ overflow: 'hidden', whiteSpace: 'nowrap' }}>
            <Checkbox
                size="small"
                disabled={disabled}
                checked={checked}
                onChange={(e) => onChange(e.target.checked)}
                sx={{ padding: '4px' }}
            />
            <Typography
                variant="caption"
                sx={{ display: 'inline-block', ml: -0.5 }}
            >
                {label.slice(0, 1).toUpperCase() + label.slice(1)}
            </Typography>
        </Grid>
    );
};

export { TemporalFiltersHook };

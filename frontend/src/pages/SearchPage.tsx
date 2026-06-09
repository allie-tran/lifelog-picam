import {
    AccessTimeRounded,
    AddAPhotoRounded,
    ArrowDropDownRounded,
    AutoAwesomeRounded,
    CloseRounded,
    DeleteRounded,
    GridViewRounded,
    HistoryRounded,
    SortRounded,
    ViewStreamRounded,
} from '@mui/icons-material';
import {
    Accordion,
    AccordionDetails,
    AccordionSummary,
    Box,
    Button,
    Checkbox,
    Chip,
    Divider,
    Drawer,
    IconButton,
    InputAdornment,
    LinearProgress,
    Pagination,
    Stack,
    TextField,
    ToggleButton,
    ToggleButtonGroup,
    Tooltip,
    Typography,
    styled,
} from '@mui/material';
import {
    CountItem,
    LocationSummaryItem,
    deleteImages,
    parseQueryFilters,
    searchImages,
} from 'apis/browsing';
import ResultSummaryBar from 'components/ResultSummaryBar';
import { FaceFiltersHook } from 'components/FaceFilters';
import ImageDropSearch from 'components/ImageDropSearch';
import ImageWithDate from 'components/ImageWithDate';
import LifelogEvent from 'components/LifelogEvent';
import { LocationFiltersHook } from 'components/LocationFilters';
import { TemporalFiltersHook } from 'components/TemporalFilters';
import dayjs from 'dayjs';
import timezone from 'dayjs/plugin/timezone';
import utc from 'dayjs/plugin/utc';
import React, { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';
import { setDevice } from 'reducers/auth';
import { setLoading } from 'reducers/feedback';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import { clearHistory, pushToHistory, removeFromHistory, setSearchQuery } from 'reducers/search';
import { setZoomedImage } from 'reducers/zoomedImage';
import useSWR from 'swr';
import '../App.css';
import { ImageZoom } from '../components/ImageZoom';

dayjs.extend(utc);
dayjs.extend(timezone);

const PAGE_SIZE = 20;

const SearchPage = () => {
    const dispatch = useAppDispatch();
    const [searchParams, _] = useSearchParams();
    const device = searchParams.get('device') || '';
    const searchQuery = useAppSelector((state) => state.search.query);
    const searchHistory = useAppSelector((state) => state.search.history);

    useEffect(() => {
        if (device) dispatch(setDevice(device));
    }, [device]);

    // View Settings
    const [sortBy, setSortBy] = useState<'time' | 'relevance'>('relevance');
    const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
    const [viewMode, setViewMode] = useState<'images' | 'events'>('images');
    const [page, setPage] = useState(1);

    // Search Settings
    const [textQuery, setTextQuery] = useState(searchQuery.text || '');
    const [useImageInput, setUseImageInput] = useState<boolean>(false);

    useEffect(() => {
        if (!textQuery.trim()) return;
        const timer = setTimeout(() => {
            parseQueryFilters(textQuery, device)
                .then((parsed) => {
                    dispatch(setSearchQuery(parsed));
                    const hasTemporalFilter =
                        (parsed.timeOfDays?.length ?? 0) > 0 ||
                        (parsed.dayOfWeeks?.length ?? 0) > 0 ||
                        (parsed.months?.length ?? 0) > 0 ||
                        (parsed.years?.length ?? 0) > 0 ||
                        (parsed.customRanges?.length ?? 0) > 0;
                    if (hasTemporalFilter) setFilterShown('temporal');
                })
                .catch(() => {});
        }, 800);
        return () => clearTimeout(timer);
    }, [textQuery, dispatch]);

    const [filterShown, setFilterShown] = useState<
        'temporal' | 'location' | 'faces' | null
    >(null);

    const {
        renderFilterOptions: LocationFilterOptions,
        renderMap,
        renderClearButton: LocationClearButton,
        nothingIsSelected: locationNothingIsSelected,
    } = LocationFiltersHook();
    const {
        renderFilterOptions: FaceFilterOptions,
        renderFaceExplorer,
        renderClearButton: FaceClearButton,
        nothingIsSelected: faceNothingIsSelected,
    } = FaceFiltersHook();

    // Annotation Settings
    const [isSelecting, setIsSelecting] = useState(false);
    const [selectedImages, setSelectedImages] = useState<string[]>([]);

    const [searchSummaryData, setSearchSummaryData] = React.useState<{
        topLocations: LocationSummaryItem[];
        topCountries: CountItem[];
        topPeople: CountItem[];
    } | null>(null);

    // Endpoints
    const {
        data: searchEvents,
        isLoading,
        mutate,
    } = useSWR(
        ['search', device, sortBy, searchQuery],
        () =>
            searchImages(device, searchQuery, sortBy).then(
                ({ segments, topLocations, topCountries, topPeople }) => {
                    dispatch(setLoading(false));
                    setPage(1);
                    setSearchSummaryData({
                        topLocations,
                        topCountries,
                        topPeople,
                    });
                    if (segments.length > 0) setFilterShown('temporal');
                    if (sortBy === 'relevance') {
                        setSortOrder('desc');
                        return segments.slice().reverse();
                    } else {
                        setSortOrder('desc'); // time: newest first by default
                    }
                    return segments;
                }
            ),
        { revalidateOnFocus: false }
    );

    const results = useMemo(() => {
        if (!searchEvents) return [];
        if (sortBy === 'time') {
            return [...searchEvents].sort((a, b) => {
                const aTime = new Date(a[0]?.timestamp ?? 0).getTime();
                const bTime = new Date(b[0]?.timestamp ?? 0).getTime();
                return sortOrder === 'asc' ? aTime - bTime : bTime - aTime;
            });
        }
        // relevance: fetcher stored segments reversed (least relevant first)
        // desc = most relevant first → reverse back; asc = least relevant first → keep
        if (sortOrder === 'desc') {
            return searchEvents.slice().reverse();
        }
        return searchEvents;
    }, [searchEvents, sortOrder, sortBy]);

    const [deleted, setDeleted] = useState<string[]>([]);

    const images = useMemo(() => {
        if (results.length !== 0) {
            return results.reduce((acc, segment) => {
                return [...acc, ...segment];
            });
        }
        return [];
    }, [results]);

    const {
        renderFilterOptions,
        renderHeatmap,
        renderClearButton,
        nothingIsSelected,
    } = TemporalFiltersHook({
        resultImages: images,
        onDeleteImage: (path) => setDeleted((prev) => [...prev, path]),
        onZoomImage: (path, isVideo) =>
            dispatch(setZoomedImage({ image: path, isVideo })),
    });

    const resultSummary = useMemo(() => {
        if (!images.length) return null;
        const timestamps = images.map((img) => dayjs.utc(img.timestamp));
        const earliest = timestamps.reduce((a, b) => (a.isBefore(b) ? a : b));
        const latest = timestamps.reduce((a, b) => (a.isAfter(b) ? a : b));
        const sameDay =
            earliest.format('YYYY-MM-DD') === latest.format('YYYY-MM-DD');
        const dateRange = sameDay
            ? earliest.tz(images[0].timezone || 'UTC').format('D MMM YYYY')
            : `${earliest.tz(images[0].timezone || 'UTC').format('D MMM YYYY')} – ${latest.tz(images[images.length - 1].timezone || 'UTC').format('D MMM YYYY')}`;

        const activityCounts: Record<string, number> = {};
        for (const img of images) {
            if (img.activity) {
                activityCounts[img.activity] =
                    (activityCounts[img.activity] ?? 0) + 1;
            }
        }
        const topActivities = Object.entries(activityCounts)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 3)
            .map(([name]) => name);

        return {
            dateRange,
            eventCount: results.length,
            photoCount: images.length,
            topActivities,
            topLocations: searchSummaryData?.topLocations ?? [],
            topCountries: searchSummaryData?.topCountries ?? [],
            topPeople: searchSummaryData?.topPeople ?? [],
        };
    }, [images, results, searchSummaryData]);

    const triggerSearch = React.useCallback(() => {
        const full = { ...searchQuery, text: textQuery };
        dispatch(pushToHistory(full));
        dispatch(setSearchQuery({ text: textQuery }));
    }, [searchQuery, textQuery, dispatch]);

    const restoreFromHistory = React.useCallback((entry: typeof searchQuery) => {
        setTextQuery(entry.text || '');
        dispatch(setSearchQuery(entry));
    }, [dispatch]);

    const handleAppendToQuery = React.useCallback((text: string) => {
        setTextQuery((prev) => (prev.trim() ? `${prev.trim()} ${text}` : text));
    }, []);

    const handleAddLocationFilter = React.useCallback(
        (id: string) => {
            const existing = searchQuery.locationIds ?? [];
            if (!existing.includes(id)) {
                dispatch(setSearchQuery({ locationIds: [...existing, id] }));
            }
        },
        [searchQuery.locationIds, dispatch]
    );

    const handleAddPersonFilter = React.useCallback(
        (id: string) => {
            const existing = searchQuery.peopleIds ?? [];
            if (!existing.includes(id)) {
                dispatch(setSearchQuery({ peopleIds: [...existing, id] }));
            }
        },
        [searchQuery.peopleIds, dispatch]
    );

    const deleteRow = (imagePaths: string[]) => {
        dispatch(setLoading(true));
        deleteImages(device, imagePaths).then(() => {
            setDeleted((prev) => [...prev, ...imagePaths]);
            dispatch(setLoading(false));
        });
    };

    const currentPageResults =
        results?.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE) || [];

    const currentPageImages = (
        images?.slice((page - 1) * PAGE_SIZE * 2, page * PAGE_SIZE * 2) || []
    ).filter((img) => !deleted.includes(img.imagePath));

    return (
        <>
            <Drawer
                anchor="left"
                open={true}
                variant="permanent"
                slotProps={{
                    paper: {
                        sx: {
                            width: 325,
                            padding: 2,
                            ml: 6,
                            backgroundColor: '#f4f6e8',
                            zIndex: 1300,
                        },
                    },
                }}
            >
                <Typography
                    variant="h6"
                    color="primary"
                    fontWeight="bold"
                    gutterBottom
                >
                    Search
                </Typography>
                <Typography variant="caption">
                    Type in a prompt in natural language
                </Typography>
                <TextField
                    variant="outlined"
                    multiline
                    rows={3}
                    value={textQuery}
                    onChange={(e) => setTextQuery(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                            e.preventDefault();
                            triggerSearch();
                        }
                    }}
                    sx={{ marginY: 1 }}
                    slotProps={{
                        input: {
                            endAdornment: (
                                <InputAdornment position="end">
                                    <IconButton
                                        onClick={() =>
                                            setUseImageInput((prev) => !prev)
                                        }
                                        edge="end"
                                    >
                                        <AddAPhotoRounded
                                            color={
                                                useImageInput
                                                    ? 'primary'
                                                    : 'inherit'
                                            }
                                        />
                                    </IconButton>
                                </InputAdornment>
                            ),
                        },
                    }}
                />
                <ImageDropSearch visible={useImageInput} />
                {searchHistory.length > 0 && (
                    <Box sx={{ mt: 0.5, mb: 0.5 }}>
                        <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 0.25 }}>
                            <Typography variant="caption" color="text.secondary" sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                <HistoryRounded sx={{ fontSize: 13 }} /> Recent
                            </Typography>
                            <Tooltip title="Clear history">
                                <IconButton size="small" sx={{ p: 0.25 }} onClick={() => dispatch(clearHistory())}>
                                    <CloseRounded sx={{ fontSize: 12 }} />
                                </IconButton>
                            </Tooltip>
                        </Stack>
                        <Stack spacing={0.25}>
                            {searchHistory.slice(0, 8).map((entry, i) => {
                                const filterCount = [
                                    entry.timeOfDays?.length,
                                    entry.dayOfWeeks?.length,
                                    entry.months?.length,
                                    entry.years?.length,
                                    entry.customRanges?.length,
                                    entry.locationIds?.length,
                                    entry.peopleIds?.length,
                                    entry.countries?.length,
                                ].reduce((sum, n) => sum + (n || 0), 0);
                                return (
                                    <Stack key={i} direction="row" alignItems="center" sx={{ '&:hover .remove-btn': { opacity: 1 } }}>
                                        <Button
                                            size="small"
                                            variant="text"
                                            startIcon={<HistoryRounded sx={{ fontSize: 13, color: 'text.disabled' }} />}
                                            onClick={() => restoreFromHistory(entry)}
                                            sx={{
                                                flex: 1,
                                                justifyContent: 'flex-start',
                                                textTransform: 'none',
                                                py: 0.25,
                                                px: 0.75,
                                                minHeight: 0,
                                                color: 'text.primary',
                                                '& .MuiButton-startIcon': { mr: 0.5 },
                                            }}
                                        >
                                            <Typography noWrap sx={{ fontSize: '12px', maxWidth: 185 }}>
                                                {entry.text || '(filters only)'}
                                            </Typography>
                                            {filterCount > 0 && (
                                                <Typography sx={{ fontSize: '10px', color: 'text.secondary', ml: 0.5, flexShrink: 0 }}>
                                                    +{filterCount}
                                                </Typography>
                                            )}
                                        </Button>
                                        <IconButton
                                            className="remove-btn"
                                            size="small"
                                            sx={{ p: 0.25, opacity: 0, transition: 'opacity 0.15s' }}
                                            onClick={() => dispatch(removeFromHistory(i))}
                                        >
                                            <CloseRounded sx={{ fontSize: 11 }} />
                                        </IconButton>
                                    </Stack>
                                );
                            })}
                        </Stack>
                    </Box>
                )}
                <StyledAccordion
                    square
                    elevation={0}
                    expanded={filterShown === 'temporal'}
                    onChange={() =>
                        setFilterShown((prev) =>
                            prev === 'temporal' ? null : 'temporal'
                        )
                    }
                >
                    <AccordionSummary>
                        <Typography variant="subtitle1" fontWeight="bold">
                            <ArrowDropDownRounded
                                color="primary"
                                fontSize="large"
                                sx={{
                                    verticalAlign: 'middle',
                                    transition: 'transform 0.3s',
                                    transform:
                                        filterShown === 'temporal'
                                            ? 'rotate(180deg)'
                                            : 'rotate(0deg)',
                                }}
                            />
                            Temporal Filter
                            {!nothingIsSelected && (
                                <Chip
                                    label="Applied"
                                    color="primary"
                                    sx={{ ml: 1 }}
                                    variant="outlined"
                                />
                            )}
                        </Typography>
                    </AccordionSummary>
                    <AccordionDetails sx={{ padding: 0 }}>
                        {renderFilterOptions()}
                    </AccordionDetails>
                </StyledAccordion>
                <StyledAccordion
                    square
                    elevation={0}
                    expanded={filterShown === 'location'}
                    onChange={() =>
                        setFilterShown((prev) =>
                            prev === 'location' ? null : 'location'
                        )
                    }
                >
                    <AccordionSummary>
                        <Typography variant="subtitle1" fontWeight="bold">
                            <ArrowDropDownRounded
                                color="primary"
                                fontSize="large"
                                sx={{
                                    verticalAlign: 'middle',
                                    transition: 'transform 0.3s',
                                    transform:
                                        filterShown === 'location'
                                            ? 'rotate(180deg)'
                                            : 'rotate(0deg)',
                                }}
                            />
                            Location Filter
                            {!locationNothingIsSelected && (
                                <Chip
                                    label="Applied"
                                    color="primary"
                                    sx={{ ml: 1 }}
                                    variant="outlined"
                                />
                            )}
                        </Typography>
                    </AccordionSummary>
                    <AccordionDetails sx={{ padding: 0 }}>
                        {LocationFilterOptions()}
                    </AccordionDetails>
                </StyledAccordion>
                <StyledAccordion
                    square
                    elevation={0}
                    expanded={filterShown === 'faces'}
                    onChange={() =>
                        setFilterShown((prev) =>
                            prev === 'faces' ? null : 'faces'
                        )
                    }
                >
                    <AccordionSummary>
                        <Typography variant="subtitle1" fontWeight="bold">
                            <ArrowDropDownRounded
                                color="primary"
                                fontSize="large"
                                sx={{
                                    verticalAlign: 'middle',
                                    transition: 'transform 0.3s',
                                    transform:
                                        filterShown === 'faces'
                                            ? 'rotate(180deg)'
                                            : 'rotate(0deg)',
                                }}
                            />
                            People Filter
                        </Typography>
                        {!faceNothingIsSelected && (
                            <Chip
                                label="Applied"
                                color="primary"
                                sx={{ ml: 1 }}
                                variant="outlined"
                            />
                        )}
                    </AccordionSummary>
                    <AccordionDetails sx={{ padding: 0 }}>
                        {FaceFilterOptions()}
                    </AccordionDetails>
                </StyledAccordion>
                <Stack
                    direction="row"
                    justifyContent="flex-end"
                    spacing={2}
                    sx={{ mt: 2 }}
                >
                    {filterShown === 'temporal' && renderClearButton()}
                    {filterShown === 'location' && LocationClearButton()}
                    {filterShown === 'faces' && FaceClearButton()}
                    <Button
                        variant="contained"
                        color="secondary"
                        sx={{
                            textTransform: 'none',
                            width: 80,
                        }}
                        onClick={triggerSearch}
                    >
                        Search
                    </Button>
                </Stack>
            </Drawer>

            <Box sx={{ paddingLeft: '325px' }}>
                <Box id="app" sx={{ width: '100%' }} />
                <Stack direction="row" spacing={0.5} sx={{ width: '100%' }}>
                    <Box
                        sx={{
                            width: 8,
                            height: 'auto',
                            backgroundColor: 'primary.main',
                        }}
                    />
                    <Stack
                        id="result-summary"
                        sx={{
                            width: '100%',
                            height: 'auto',
                            borderLeft: 2,
                            borderColor: 'primary.main',
                        }}
                    >
                        {resultSummary ? (
                            <Stack direction="row" spacing={1}>
                                <Typography
                                    variant="h6"
                                    color="text.primary"
                                    paddingLeft={1}
                                    sx={{ width: 180 }}
                                >
                                    Result Summary
                                </Typography>
                                <ResultSummaryBar
                                    dateRange={resultSummary.dateRange}
                                    eventCount={resultSummary.eventCount}
                                    photoCount={resultSummary.photoCount}
                                    topActivities={resultSummary.topActivities}
                                    topLocations={resultSummary.topLocations}
                                    topCountries={resultSummary.topCountries}
                                    topPeople={resultSummary.topPeople}
                                    onAppendToQuery={handleAppendToQuery}
                                    onAddLocationFilter={
                                        handleAddLocationFilter
                                    }
                                    onAddPersonFilter={handleAddPersonFilter}
                                />
                            </Stack>
                        ) : null}
                        {filterShown === 'temporal' && renderHeatmap()}
                        {filterShown === 'location' && renderMap()}
                        {filterShown === 'faces' && renderFaceExplorer()}
                    </Stack>
                </Stack>
                <Stack
                    direction="row"
                    justifyContent="flex-end"
                    alignItems="center"
                    spacing={2}
                    sx={{ marginY: 0.5, paddingRight: 2 }}
                >
                    <Stack direction="row" alignItems="center" spacing={0.75}>
                        <Typography
                            variant="caption"
                            color="text.secondary"
                            sx={{ whiteSpace: 'nowrap' }}
                        >
                            View by
                        </Typography>
                        <ToggleButtonGroup
                            value={viewMode}
                            exclusive
                            onChange={(_, v) => {
                                if (v) setViewMode(v as 'events' | 'images');
                            }}
                            size="small"
                            sx={{ height: 28 }}
                        >
                            <ToggleButton
                                value="events"
                                sx={{
                                    px: 1.25,
                                    gap: 0.5,
                                    fontSize: '11px',
                                    textTransform: 'none',
                                }}
                            >
                                <ViewStreamRounded sx={{ fontSize: 14 }} />
                                Events
                            </ToggleButton>
                            <ToggleButton
                                value="images"
                                sx={{
                                    px: 1.25,
                                    gap: 0.5,
                                    fontSize: '11px',
                                    textTransform: 'none',
                                }}
                            >
                                <GridViewRounded sx={{ fontSize: 14 }} />
                                Images
                            </ToggleButton>
                        </ToggleButtonGroup>
                    </Stack>
                    <Stack direction="row" alignItems="center" spacing={0.75}>
                        <Typography
                            variant="caption"
                            color="text.secondary"
                            sx={{ whiteSpace: 'nowrap' }}
                        >
                            Sort by
                        </Typography>
                        <ToggleButtonGroup
                            value={sortBy}
                            exclusive
                            onChange={(_, v) => {
                                if (v) setSortBy(v as 'time' | 'relevance');
                            }}
                            size="small"
                            sx={{ height: 28 }}
                        >
                            <ToggleButton
                                value="relevance"
                                sx={{
                                    px: 1.25,
                                    gap: 0.5,
                                    fontSize: '11px',
                                    textTransform: 'none',
                                }}
                            >
                                <AutoAwesomeRounded sx={{ fontSize: 14 }} />
                                Relevance
                            </ToggleButton>
                            <ToggleButton
                                value="time"
                                sx={{
                                    px: 1.25,
                                    gap: 0.5,
                                    fontSize: '11px',
                                    textTransform: 'none',
                                }}
                            >
                                <AccessTimeRounded sx={{ fontSize: 14 }} />
                                Time
                            </ToggleButton>
                        </ToggleButtonGroup>
                        <Tooltip
                            title={
                                sortOrder === 'asc'
                                    ? 'Oldest first'
                                    : 'Newest first'
                            }
                        >
                            <IconButton
                                size="small"
                                onClick={() =>
                                    setSortOrder((prev) =>
                                        prev === 'asc' ? 'desc' : 'asc'
                                    )
                                }
                                sx={{ ml: 0.25 }}
                            >
                                <SortRounded
                                    sx={{
                                        fontSize: 18,
                                        transform:
                                            sortOrder === 'asc'
                                                ? 'scaleY(-1)'
                                                : 'none',
                                        transition: 'transform 0.2s',
                                    }}
                                />
                            </IconButton>
                        </Tooltip>
                    </Stack>
                </Stack>
                <Divider flexItem sx={{ marginBottom: 2 }} />
                {isLoading ? (
                    <LinearProgress sx={{ marginBottom: 2 }} />
                ) : viewMode === 'events' ? (
                    <>
                        <Stack
                            direction="row"
                            spacing={2}
                            sx={{ width: '100%' }}
                            flexWrap="wrap"
                            useFlexGap
                        >
                            {currentPageResults.map((segment, index) => (
                                <LifelogEvent
                                    key={index}
                                    segment={segment}
                                    onChange={() => mutate()}
                                    deleteRow={deleteRow}
                                    fullTime
                                />
                            ))}
                        </Stack>
                        {page > 0 && (
                            <Pagination
                                page={page}
                                count={Math.ceil(results.length / PAGE_SIZE)}
                                color="primary"
                                sx={{
                                    display: 'flex',
                                    justifyContent: 'center',
                                    marginY: 4,
                                }}
                                onChange={(_, page) => {
                                    setPage(page);
                                    const element =
                                        document.getElementById('app');
                                    element?.scrollIntoView({
                                        behavior: 'smooth',
                                    });
                                }}
                            />
                        )}
                    </>
                ) : (
                    <>
                        {currentPageImages.length == 0 ? null : (
                            <Stack direction="row" alignItems="center">
                                <Button
                                    color="error"
                                    onClick={() => {
                                        setSelectedImages(
                                            currentPageImages.map(
                                                (img) => img.imagePath
                                            )
                                        );
                                        setIsSelecting(true);
                                    }}
                                    sx={{
                                        textTransform: 'none',
                                        marginBottom: 2,
                                    }}
                                >
                                    <DeleteRounded sx={{ marginRight: 1 }} />
                                    Delete All on This Page
                                </Button>
                            </Stack>
                        )}
                        {isSelecting && (
                            <Stack direction="row" spacing={2} marginBottom={2}>
                                <Button
                                    variant="contained"
                                    color="error"
                                    onClick={() => {
                                        deleteRow(selectedImages);
                                        setIsSelecting(false);
                                        setSelectedImages([]);
                                    }}
                                    sx={{ textTransform: 'none' }}
                                >
                                    Confirm Delete ({selectedImages.length})
                                </Button>
                                <Button
                                    variant="outlined"
                                    onClick={() => {
                                        setIsSelecting(false);
                                        setSelectedImages([]);
                                    }}
                                    sx={{ textTransform: 'none' }}
                                >
                                    Cancel
                                </Button>
                            </Stack>
                        )}
                        <Stack
                            spacing={1}
                            sx={{ flexWrap: 'wrap' }}
                            direction="row"
                            useFlexGap
                        >
                            {currentPageImages?.map((image) =>
                                deleted.includes(image.imagePath) ? null : (
                                    <ImageWithDate
                                        fontSize={'10px'}
                                        height={'200px'}
                                        image={image}
                                        onClick={() => {
                                            dispatch(
                                                setZoomedImage({
                                                    image: image.imagePath,
                                                    isVideo: image.isVideo,
                                                })
                                            );
                                        }}
                                        onDelete={() =>
                                            setDeleted([
                                                ...deleted,
                                                image.imagePath,
                                            ])
                                        }
                                        extra={
                                            isSelecting && (
                                                <Checkbox
                                                    checked={selectedImages.includes(
                                                        image.imagePath
                                                    )}
                                                    onChange={(e) => {
                                                        if (e.target.checked) {
                                                            setSelectedImages(
                                                                (prev) => [
                                                                    ...prev,
                                                                    image.imagePath,
                                                                ]
                                                            );
                                                        } else {
                                                            setSelectedImages(
                                                                (prev) =>
                                                                    prev.filter(
                                                                        (
                                                                            path
                                                                        ) =>
                                                                            path !==
                                                                            image.imagePath
                                                                    )
                                                            );
                                                        }
                                                    }}
                                                />
                                            )
                                        }
                                    />
                                )
                            )}
                        </Stack>
                        {page > 0 && images.length > PAGE_SIZE * 2 && (
                            <Pagination
                                page={page}
                                count={Math.ceil(
                                    images.length / (PAGE_SIZE * 2)
                                )}
                                color="primary"
                                sx={{
                                    display: 'flex',
                                    justifyContent: 'center',
                                    marginY: 4,
                                }}
                                onChange={(_, page) => {
                                    setPage(page);
                                    const element =
                                        document.getElementById('app');
                                    element?.scrollIntoView({
                                        behavior: 'smooth',
                                    });
                                }}
                            />
                        )}
                    </>
                )}
                <ImageZoom
                    onDelete={(imgPath?: string) => {
                        if (imgPath) {
                            setDeleted([...deleted, imgPath]);
                        }
                    }}
                />
            </Box>
        </>
    );
};

const StyledAccordion = styled(Accordion)(({ theme }) => ({
    borderRadius: theme.shape.borderRadius,
    borderColor: theme.palette.primary.main,
    backgroundColor: 'transparent',
    '&.Mui-expanded': {
        borderTop: '4px solid',
        borderColor: theme.palette.primary.main,
        borderRadius: 0,
    },
}));

export default SearchPage;

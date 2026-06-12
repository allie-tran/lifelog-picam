import {
    AccessTimeRounded,
    AddAPhotoRounded,
    ArrowDropDownRounded,
    AutoAwesomeRounded,
    CloseRounded,
    DeleteRounded,
    GridViewRounded,
    HistoryRounded,
    SendRounded,
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
import { submitImages } from 'apis/dres';
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
import React, { useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router';
import { setDevice } from 'reducers/auth';
import { setLoading, showNotification } from 'reducers/feedback';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import { clearHistory, pushToHistory, removeFromHistory } from 'reducers/search';
import { addSubmittedImages } from 'reducers/dres';
import { applyQueryToParams, parseSearchParams } from '@utils/searchParams';
import { setZoomedImage } from 'reducers/zoomedImage';
import useSWR from 'swr';
import { SearchQuery } from '@utils/types';
import '../App.css';
import { ImageZoom } from '../components/ImageZoom';
import { parseErrorResponse } from '@utils/misc';
import { THUMBNAIL_HOST_URL } from '../constants/urls';

dayjs.extend(utc);
dayjs.extend(timezone);

const PAGE_SIZE = 20;


const queryFilterChips = (entry: SearchQuery): string[] => {
    const chips: string[] = [];
    entry.timeOfDays?.forEach((t) => chips.push(t));
    entry.dayOfWeeks?.forEach((d) => chips.push(d.slice(0, 3)));
    entry.seasons?.forEach((s) => chips.push(s));
    entry.months?.forEach((m) => chips.push(m.slice(0, 3)));
    entry.years?.forEach((y) => chips.push(String(y)));
    if (entry.isMoving) chips.push('moving');
    entry.countries?.forEach((c) => chips.push(c));
    if ((entry.locationIds?.length ?? 0) > 0)
        chips.push(`${entry.locationIds!.length} place${entry.locationIds!.length > 1 ? 's' : ''}`);
    if ((entry.peopleIds?.length ?? 0) > 0)
        chips.push(`${entry.peopleIds!.length} person${entry.peopleIds!.length > 1 ? 's' : ''}`);
    return chips;
};

type SearchTextBoxHandle = { setText: (t: string) => void };

const SearchTextBox = React.memo(
    React.forwardRef<SearchTextBoxHandle, {
        initialValue: string;
        device: string;
        onTextChange: (text: string) => void;
        onSearch: () => void;
        onParseResult: (extracted: Partial<SearchQuery>) => void;
        onFilterDetected: (type: 'temporal') => void;
        imageRefs: string[];
        dragBlobUrls: string[];
        onRemoveImageRef: (ref: string) => void;
        onRemoveBlobUrl: (url: string) => void;
        onAddBlobUrl: (url: string) => void;
    }>(({
        initialValue, device, onTextChange, onSearch, onParseResult, onFilterDetected,
        imageRefs, dragBlobUrls, onRemoveImageRef, onRemoveBlobUrl, onAddBlobUrl,
    }, ref) => {
        const [textQuery, setTextQuery] = useState(initialValue);
        const [useImageInput, setUseImageInput] = useState(false);
        const [isDragOver, setIsDragOver] = useState(false);
        const submittedRef = useRef(false);
        const parseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

        useEffect(() => { setTextQuery(initialValue); onTextChange(initialValue); }, [initialValue, onTextChange]);

        useImperativeHandle(ref, () => ({
            setText: (t: string) => { setTextQuery(t); onTextChange(t); },
        }), [onTextChange]);

        const handleChange = (t: string) => {
            submittedRef.current = false;
            setTextQuery(t);
            onTextChange(t);
        };

        const handleDragOver = (e: React.DragEvent) => {
            const { types } = e.dataTransfer;
            if (types.includes('Files') || types.includes('text/uri-list')) {
                e.preventDefault();
                setIsDragOver(true);
            }
        };
        const handleDragLeave = () => setIsDragOver(false);
        const handleDrop = (e: React.DragEvent) => {
            e.preventDefault();
            setIsDragOver(false);
            const file = e.dataTransfer.files[0];
            if (file?.type.startsWith('image/')) { onAddBlobUrl(URL.createObjectURL(file)); return; }
            const url = e.dataTransfer.getData('text/uri-list') || e.dataTransfer.getData('text/plain');
            if (url?.startsWith('http')) {
                fetch(url).then(r => r.blob()).then(blob => {
                    if (blob.type.startsWith('image/')) onAddBlobUrl(URL.createObjectURL(blob));
                }).catch(() => {});
            }
        };

        useEffect(() => {
            if (!textQuery.trim() || submittedRef.current) return;
            const timer = setTimeout(() => {
                if (submittedRef.current) return;
                parseQueryFilters(textQuery, device)
                    .then((parsed) => {
                        const extracted: Partial<SearchQuery> = {};
                        if (parsed.timeOfDays?.length) extracted.timeOfDays = parsed.timeOfDays;
                        if (parsed.dayOfWeeks?.length) extracted.dayOfWeeks = parsed.dayOfWeeks;
                        if (parsed.seasons?.length) extracted.seasons = parsed.seasons;
                        if (parsed.months?.length) extracted.months = parsed.months;
                        if (parsed.years?.length) extracted.years = parsed.years;
                        if (parsed.customRanges?.length) extracted.customRanges = parsed.customRanges;
                        if (parsed.countries?.length) extracted.countries = parsed.countries;
                        if (parsed.locationIds?.length) extracted.locationIds = parsed.locationIds;
                        if (Object.keys(extracted).length > 0) onParseResult(extracted);
                        const hasTemporalFilter =
                            (parsed.timeOfDays?.length ?? 0) > 0 ||
                            (parsed.dayOfWeeks?.length ?? 0) > 0 ||
                            (parsed.months?.length ?? 0) > 0 ||
                            (parsed.years?.length ?? 0) > 0 ||
                            (parsed.customRanges?.length ?? 0) > 0;
                        if (hasTemporalFilter) onFilterDetected('temporal');
                    })
                    .catch(() => {});
            }, 800);
            parseTimerRef.current = timer;
            return () => { clearTimeout(timer); parseTimerRef.current = null; };
        }, [textQuery, device, onParseResult, onFilterDetected]);

        return (
            <>
                <Box
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                    sx={{
                        borderRadius: 1,
                        outline: isDragOver ? '2px dashed' : 'none',
                        outlineColor: 'primary.main',
                        transition: 'outline 0.1s',
                    }}
                >
                    <TextField
                        variant="outlined"
                        multiline
                        rows={3}
                        value={textQuery}
                        onChange={(e) => handleChange(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault();
                                submittedRef.current = true;
                                if (parseTimerRef.current) {
                                    clearTimeout(parseTimerRef.current);
                                    parseTimerRef.current = null;
                                }
                                onSearch();
                            }
                        }}
                        sx={{ marginY: 1, width: '100%' }}
                        slotProps={{
                            input: {
                                endAdornment: (
                                    <InputAdornment position="end">
                                        <IconButton
                                            onClick={() => setUseImageInput((prev) => !prev)}
                                            edge="end"
                                        >
                                            <AddAPhotoRounded
                                                color={
                                                    useImageInput || imageRefs.length > 0 || dragBlobUrls.length > 0
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
                </Box>
                {(imageRefs.length > 0 || dragBlobUrls.length > 0) && (
                    <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mt: 0.5 }}>
                        {imageRefs.map((r) => (
                            <Box key={r} sx={{ position: 'relative', display: 'inline-flex' }}>
                                <Box
                                    component="img"
                                    src={`${THUMBNAIL_HOST_URL}/${device}/${r.replace(/\.[^.]+$/, '.webp')}`}
                                    sx={{ height: 64, width: 'auto', borderRadius: 1, border: '2px solid', borderColor: 'secondary.main', display: 'block' }}
                                />
                                <IconButton
                                    size="small"
                                    onClick={() => onRemoveImageRef(r)}
                                    sx={{ position: 'absolute', top: -8, right: -8, bgcolor: 'background.paper', border: '1px solid', borderColor: 'divider', p: '2px', '&:hover': { bgcolor: 'error.light' } }}
                                >
                                    <CloseRounded sx={{ fontSize: 12 }} />
                                </IconButton>
                            </Box>
                        ))}
                        {dragBlobUrls.map((url) => (
                            <Box key={url} sx={{ position: 'relative', display: 'inline-flex' }}>
                                <Box
                                    component="img"
                                    src={url}
                                    sx={{ height: 64, width: 'auto', borderRadius: 1, border: '2px solid', borderColor: 'primary.main', display: 'block' }}
                                />
                                <IconButton
                                    size="small"
                                    onClick={() => onRemoveBlobUrl(url)}
                                    sx={{ position: 'absolute', top: -8, right: -8, bgcolor: 'background.paper', border: '1px solid', borderColor: 'divider', p: '2px', '&:hover': { bgcolor: 'error.light' } }}
                                >
                                    <CloseRounded sx={{ fontSize: 12 }} />
                                </IconButton>
                            </Box>
                        ))}
                    </Stack>
                )}
                <ImageDropSearch
                    visible={useImageInput}
                    onImageSelect={(blobUrl) => {
                        onAddBlobUrl(blobUrl);
                        setUseImageInput(false);
                    }}
                />
            </>
        );
    })
);

const SearchPage = () => {
    const dispatch = useAppDispatch();
    const [searchParams, setSearchParams] = useSearchParams();
    const device = searchParams.get('device') || '';
    const searchQuery = useMemo(() => parseSearchParams(searchParams), [searchParams]);
    const searchHistory = useAppSelector((state) => state.search.history);

    // View Settings
    const [sortBy, setSortBy] = useState<'time' | 'relevance'>('relevance');
    const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
    const [viewMode, setViewMode] = useState<'images' | 'events'>('images');
    const [page, setPage] = useState(1);

    // textQuery lives in SearchTextBox child — read via ref to avoid re-renders on typing
    const textQueryRef = useRef(searchParams.get('q') || '');
    const searchTextBoxRef = useRef<SearchTextBoxHandle>(null);

    // Drag-and-drop / camera image blobs (stay here — SWR key depends on them)
    const [dragBlobUrls, setDragBlobUrls] = useState<string[]>([]);

    const addBlobUrl = useCallback((url: string) => setDragBlobUrls((prev) => [...prev, url]), []);
    const removeBlobUrl = useCallback((url: string) => {
        URL.revokeObjectURL(url);
        setDragBlobUrls((prev) => prev.filter((u) => u !== url));
    }, []);

    const removeImageRef = useCallback((ref: string) => {
        setSearchParams((prev) => {
            const p = new URLSearchParams(prev);
            const rest = p.getAll('imageRef').filter((r) => r !== ref);
            p.delete('imageRef');
            rest.forEach((r) => p.append('imageRef', r));
            return p;
        });
    }, [setSearchParams]);

    const handleTextChange = useCallback((t: string) => { textQueryRef.current = t; }, []);

    // Track last parse output so we only apply a field when the parser's answer changes.
    // This prevents re-adding a filter the user manually removed while the text stays the same.
    const lastParsedRef = useRef<Partial<SearchQuery>>({});

    const onParseResult = useCallback((extracted: Partial<SearchQuery>) => {
        const last = lastParsedRef.current;
        lastParsedRef.current = extracted;
        setSearchParams((prev) => {
            const toApply: Partial<SearchQuery> = {};
            for (const _key of Object.keys(extracted)) {
                const key = _key as keyof SearchQuery;
                const newVal = extracted[key] as unknown[];
                const lastVal = (last[key] as unknown[]) ?? [];
                const changed =
                    newVal.length !== lastVal.length ||
                    newVal.some((v, i) => v !== lastVal[i]);
                if (changed) (toApply as any)[key] = extracted[key];
            }
            if (!Object.keys(toApply).length) return prev;
            return applyQueryToParams(toApply, new URLSearchParams(prev));
        }, { replace: true });
    }, [setSearchParams]);

    const onFilterDetected = useCallback((type: 'temporal') => {
        setFilterShown(type);
    }, []);

    const prevDeviceRef = useRef<string | null>(null);
    useEffect(() => {
        if (!device) return;
        if (prevDeviceRef.current !== null && device !== prevDeviceRef.current) {
            setSearchParams({ device });
            textQueryRef.current = '';
            searchTextBoxRef.current?.setText('');
            lastParsedRef.current = {};
        }
        prevDeviceRef.current = device;
        dispatch(setDevice(device));
    }, [device]); // eslint-disable-line react-hooks/exhaustive-deps

    const [filterShown, setFilterShown] = useState<
        'temporal' | 'location' | 'faces' | null
    >(null);

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

    const imageRefs = searchParams.getAll('imageRef');
    const blobQuery = searchParams.get('mode') === 'similar' ? (searchParams.get('query') || undefined) : undefined;
    const hasSearchInput = !!(
        imageRefs.length || blobQuery || dragBlobUrls.length ||
        searchQuery.text ||
        searchQuery.timeOfDays?.length || searchQuery.dayOfWeeks?.length ||
        searchQuery.months?.length || searchQuery.years?.length ||
        searchQuery.customRanges?.length || searchQuery.countries?.length ||
        searchQuery.locationIds?.length || searchQuery.bounds ||
        searchQuery.peopleIds?.length
    );

    // Endpoints
    const {
        data: searchEvents,
        isLoading,
        mutate,
    } = useSWR(
        hasSearchInput ? ['search', sortBy, searchParams.toString(), dragBlobUrls.join(',')] : null,
        async () => {
            const blobUrls = dragBlobUrls.length > 0 ? dragBlobUrls : (blobQuery ? [blobQuery] : []);
            const imageBlobs: Blob[] = [];
            for (const url of blobUrls) {
                try {
                    const r = await fetch(url);
                    imageBlobs.push(await r.blob());
                } catch {
                    // expired or invalid — skip
                }
            }
            const options = (imageRefs.length || imageBlobs.length)
                ? { imagePaths: imageRefs, imageBlobs }
                : undefined;
            const { segments, topLocations, topCountries, topPeople } =
                await searchImages(device, searchQuery, sortBy, options);
            dispatch(setLoading(false));
            setPage(1);
            setSearchSummaryData({ topLocations, topCountries, topPeople });
            if (sortBy === 'relevance') {
                setSortOrder('desc');
                return segments.slice().reverse();
            }
            setSortOrder('desc');
            return segments;
        },
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

    const triggerSearch = useCallback(() => {
        const text = textQueryRef.current;
        const full = { ...searchQuery, text };
        dispatch(pushToHistory(full));
        setSearchParams((prev) => {
            const p = new URLSearchParams(prev);
            if (text) p.set('q', text); else p.delete('q');
            return p;
        });
    }, [searchQuery, dispatch, setSearchParams]);

    const restoreFromHistory = useCallback((entry: SearchQuery) => {
        const text = entry.text || '';
        textQueryRef.current = text;
        searchTextBoxRef.current?.setText(text);
        setSearchParams((prev) => {
            const p = applyQueryToParams(entry, new URLSearchParams());
            const device = prev.get('device');
            if (device) p.set('device', device);
            return p;
        });
    }, [setSearchParams]);

    const handleAppendToQuery = useCallback((text: string) => {
        const current = textQueryRef.current;
        const newText = current.trim() ? `${current.trim()} ${text}` : text;
        textQueryRef.current = newText;
        searchTextBoxRef.current?.setText(newText);
        setSearchParams((prev) => {
            const p = new URLSearchParams(prev);
            if (newText) p.set('q', newText); else p.delete('q');
            return p;
        });
    }, [setSearchParams]);

    const handleAddLocationFilter = React.useCallback((id: string, name: string) => {
        setSearchParams((prev) => {
            const existing = prev.get('locationIds')?.split(',').filter(Boolean) ?? [];
            if (existing.includes(id)) return prev;
            const p = new URLSearchParams(prev);
            p.set('locationIds', [...existing, id].join(','));
            const labels: Record<string, string> = JSON.parse(p.get('locationLabels') || '{}');
            labels[id] = name;
            p.set('locationLabels', JSON.stringify(labels));
            return p;
        });
    }, [setSearchParams]);

    const [highlightedLocationId, setHighlightedLocationId] = React.useState<string | null>(null);

    const {
        renderFilterOptions: LocationFilterOptions,
        renderMap,
        renderClearButton: LocationClearButton,
        nothingIsSelected: locationNothingIsSelected,
    } = LocationFiltersHook({
        resultLocations: searchSummaryData?.topLocations ?? [],
        onAddLocationFilter: handleAddLocationFilter,
        highlightedLocationId,
    });

    const handleAddPersonFilter = React.useCallback((id: string) => {
        setSearchParams((prev) => {
            const existing = prev.get('peopleIds')?.split(',').filter(Boolean) ?? [];
            if (existing.includes(id)) return prev;
            const p = new URLSearchParams(prev);
            p.set('peopleIds', [...existing, id].join(','));
            return p;
        });
    }, [setSearchParams]);

    const { evaluationId, sessionId, currentTask } = useAppSelector((s) => s.dres);
    const dresReady = !!(evaluationId && sessionId);

    const deleteRow = (imagePaths: string[]) => {
        dispatch(setLoading(true));
        deleteImages(device, imagePaths).then(() => {
            setDeleted((prev) => [...prev, ...imagePaths]);
            dispatch(setLoading(false));
        });
    };

    // DRES page-select submit flow
    const [isDresSelecting, setIsDresSelecting] = useState(false);
    const [dresSelectedImages, setDresSelectedImages] = useState<string[]>([]);

    const handleDresSelectPage = () => {
        setDresSelectedImages(currentPageImages.map((img) => img.imagePath));
        setIsDresSelecting(true);
    };

    const handleDresConfirmSubmit = () => {
        if (!dresReady || !dresSelectedImages.length) return;
        const toSubmit = [...dresSelectedImages];
        // Optimistically mark as submitted and close selection mode immediately
        dispatch(addSubmittedImages(toSubmit));
        setDresSelectedImages([]);
        setIsDresSelecting(false);
        // Fire requests in the background without blocking interaction
        (async () => {
            try {
                const r = await submitImages({ images: toSubmit, evaluationId: evaluationId!, sessionId: sessionId! });
                dispatch(showNotification({
                    message: `DRES: ${r.verdict} — submitted ${toSubmit.length} images`,
                    type: r.severity,
                }));
            } catch (err: any) {
                const reason = err.response.data?.description || parseErrorResponse(err) || 'Unknown error';
                dispatch(showNotification({ message: reason, type: 'error' }));
            }
        })();
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
                <SearchTextBox
                    ref={searchTextBoxRef}
                    initialValue={searchParams.get('q') || ''}
                    device={device}
                    onTextChange={handleTextChange}
                    onSearch={triggerSearch}
                    onParseResult={onParseResult}
                    onFilterDetected={onFilterDetected}
                    imageRefs={imageRefs}
                    dragBlobUrls={dragBlobUrls}
                    onRemoveImageRef={removeImageRef}
                    onRemoveBlobUrl={removeBlobUrl}
                    onAddBlobUrl={addBlobUrl}
                />
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
                                const chips = queryFilterChips(entry);
                                return (
                                    <Stack key={i} direction="row" alignItems="flex-start" sx={{ '&:hover .remove-btn': { opacity: 1 } }}>
                                        <Button
                                            size="small"
                                            variant="text"
                                            startIcon={<HistoryRounded sx={{ fontSize: 13, color: 'text.disabled', mt: 0.25 }} />}
                                            onClick={() => restoreFromHistory(entry)}
                                            sx={{
                                                flex: 1,
                                                justifyContent: 'flex-start',
                                                alignItems: 'flex-start',
                                                textTransform: 'none',
                                                py: 0.25,
                                                px: 0.75,
                                                minHeight: 0,
                                                color: 'text.primary',
                                                '& .MuiButton-startIcon': { mr: 0.5 },
                                            }}
                                        >
                                            <Box>
                                                <Typography noWrap sx={{ fontSize: '12px', maxWidth: 220, lineHeight: 1.3 }}>
                                                    {entry.text || '(filters only)'}
                                                </Typography>
                                                {chips.length > 0 && (
                                                    <Stack direction="row" flexWrap="wrap" gap={0.25} sx={{ mt: 0.25 }}>
                                                        {chips.map((chip, j) => (
                                                            <Chip
                                                                key={j}
                                                                label={chip}
                                                                size="small"
                                                                sx={{ fontSize: '9px', height: 14, '& .MuiChip-label': { px: 0.5 } }}
                                                            />
                                                        ))}
                                                    </Stack>
                                                )}
                                            </Box>
                                        </Button>
                                        <IconButton
                                            className="remove-btn"
                                            size="small"
                                            sx={{ p: 0.25, opacity: 0, transition: 'opacity 0.15s', mt: 0.25 }}
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

            <Drawer
                anchor="right"
                open={filterShown === 'location'}
                variant="persistent"
                slotProps={{
                    paper: {
                        sx: {
                            width: 340,
                            p: 2,
                            paddingTop: 8,
                            zIndex: 1200,
                        },
                    },
                }}
            >
                {renderMap()}
            </Drawer>

            <Box sx={{ paddingLeft: '325px', paddingRight: filterShown === 'location' ? '340px' : 0 }}>
                <Box id="app" sx={{ width: '100%' }} />
                    <Stack
                        id="result-summary"
                        spacing={2}
                        sx={{
                            width: '100%',
                            height: 'auto',
                        }}
                    >
                        {resultSummary ? (
                            <Stack direction="row" spacing={1}>
                                <ResultSummaryBar
                                    dateRange={resultSummary.dateRange}
                                    eventCount={resultSummary.eventCount}
                                    photoCount={resultSummary.photoCount}
                                    topActivities={resultSummary.topActivities}
                                    topLocations={resultSummary.topLocations}
                                    topCountries={resultSummary.topCountries}
                                    topPeople={resultSummary.topPeople}
                                    onAppendToQuery={handleAppendToQuery}
                                    onAddLocationFilter={handleAddLocationFilter}
                                    onAddPersonFilter={handleAddPersonFilter}
                                    onHighlightLocation={setHighlightedLocationId}
                                />
                            </Stack>
                        ) : null}
                        {renderHeatmap()}
                        {filterShown === 'faces' && renderFaceExplorer()}
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
                        {currentPageImages.length === 0 ? null : (
                            <Stack direction="row" alignItems="center" spacing={1}>
                                <Button
                                    color="error"
                                    onClick={() => {
                                        setSelectedImages(currentPageImages.map((img) => img.imagePath));
                                        setIsSelecting(true);
                                    }}
                                    sx={{ textTransform: 'none', marginBottom: 2 }}
                                >
                                    <DeleteRounded sx={{ marginRight: 1 }} />
                                    Delete All on This Page
                                </Button>
                                {dresReady && (
                                    <Tooltip title={currentTask ? `Submit to: ${currentTask.name}` : 'Select images on this page to submit to DRES'}>
                                        <Button
                                            color="success"
                                            onClick={handleDresSelectPage}
                                            sx={{ textTransform: 'none', marginBottom: 2 }}
                                            startIcon={<SendRounded />}
                                        >
                                            Submit Page ({currentPageImages.length})
                                        </Button>
                                    </Tooltip>
                                )}
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
                                    onClick={() => { setIsSelecting(false); setSelectedImages([]); }}
                                    sx={{ textTransform: 'none' }}
                                >
                                    Cancel
                                </Button>
                            </Stack>
                        )}
                        {isDresSelecting && (
                            <Stack direction="row" spacing={2} marginBottom={2} alignItems="center">
                                <Button
                                    variant="contained"
                                    color="success"
                                    onClick={handleDresConfirmSubmit}
                                    disabled={dresSelectedImages.length === 0}
                                    startIcon={<SendRounded />}
                                    sx={{ textTransform: 'none' }}
                                >
                                    Submit ({dresSelectedImages.length})
                                </Button>
                                <Button
                                    variant="outlined"
                                    onClick={() => { setIsDresSelecting(false); setDresSelectedImages([]); }}
                                    sx={{ textTransform: 'none' }}
                                >
                                    Cancel
                                </Button>
                                <Typography variant="caption" color="text.secondary">
                                    Click images to deselect
                                </Typography>
                            </Stack>
                        )}
                        <Stack
                            spacing={1}
                            sx={{ flexWrap: 'wrap' }}
                            direction="row"
                            useFlexGap
                        >
                            {currentPageImages?.map((image) => {
                                if (deleted.includes(image.imagePath)) return null;
                                const isDresSelected = dresSelectedImages.includes(image.imagePath);
                                return (
                                    <Box
                                        key={image.imagePath}
                                        sx={{
                                            borderRadius: '10px',
                                            outline: isDresSelected ? '3px solid #4caf50' : 'none',
                                        }}
                                    >
                                        <ImageWithDate
                                            fontSize={'10px'}
                                            height={'200px'}
                                            image={image}
                                            onClick={() => {
                                                if (isDresSelecting) {
                                                    setDresSelectedImages((prev) =>
                                                        isDresSelected
                                                            ? prev.filter((p) => p !== image.imagePath)
                                                            : [...prev, image.imagePath]
                                                    );
                                                } else {
                                                    dispatch(setZoomedImage({ image: image.imagePath, isVideo: image.isVideo }));
                                                }
                                            }}
                                            onDelete={() => setDeleted([...deleted, image.imagePath])}
                                            extra={
                                                <>
                                                    {isSelecting && (
                                                        <Checkbox
                                                            checked={selectedImages.includes(image.imagePath)}
                                                            onChange={(e) => {
                                                                if (e.target.checked) {
                                                                    setSelectedImages((prev) => [...prev, image.imagePath]);
                                                                } else {
                                                                    setSelectedImages((prev) => prev.filter((p) => p !== image.imagePath));
                                                                }
                                                            }}
                                                        />
                                                    )}
                                                    {isDresSelecting && (
                                                        <Checkbox
                                                            checked={isDresSelected}
                                                            sx={{ color: 'success.main', '&.Mui-checked': { color: 'success.main' } }}
                                                            onChange={(e) => {
                                                                if (e.target.checked) {
                                                                    setDresSelectedImages((prev) => [...prev, image.imagePath]);
                                                                } else {
                                                                    setDresSelectedImages((prev) => prev.filter((p) => p !== image.imagePath));
                                                                }
                                                            }}
                                                        />
                                                    )}
                                                </>
                                            }
                                        />
                                    </Box>
                                );
                            })}
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

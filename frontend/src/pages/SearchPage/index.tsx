import {
    AccessTimeRounded,
    ArrowBackRounded,
    ArrowDropDownRounded,
    AutoAwesomeRounded,
    ClearAllRounded,
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
    Pagination,
    Skeleton,
    Stack,
    ToggleButton,
    ToggleButtonGroup,
    Tooltip,
    Typography,
    styled,
} from '@mui/material';
import {
    CountItem,
    HeatmapData,
    LocationSummaryItem,
    deleteImages,
    searchImages,
} from 'apis/browsing';
import { submitImages } from 'apis/dres';
import { logEvent } from 'utils/vbsLog';
import ResultSummaryBar, { ResultSummaryBarSkeleton } from 'components/search/ResultSummaryBar';
import { FaceFiltersHook } from 'components/faces/FaceFilters';
import ImageWithDate from 'components/common/ImageWithDate';
import LifelogEvent, { LifelogEventSkeleton } from 'components/browse/LifelogEvent';
import { LocationFiltersHook } from 'components/spatial/LocationFilters';
import { TemporalFiltersHook } from 'components/temporal/TemporalFilters';
import dayjs from 'dayjs';
import timezone from 'dayjs/plugin/timezone';
import utc from 'dayjs/plugin/utc';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { setDevice } from 'reducers/auth';
import { setLoading, showNotification } from 'reducers/feedback';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import { store } from 'reducers/store';
import { clearHistory, pushToHistory, removeFromHistory } from 'reducers/search';
import { addSubmittedImages } from 'reducers/dres';
import { applyQueryToParams, parseSearchParams } from '@utils/searchParams';
import { setZoomedImage } from 'reducers/zoomedImage';
import useSWR from 'swr';
import { SearchQuery } from '@utils/types';
import '../../App.css';
import { ImageZoom } from 'components/image/ImageZoom';
import { parseErrorResponse } from '@utils/misc';
import { PAGE_SIZE, queryFilterChips } from './helpers';
import SearchTextBox, { SearchTextBoxHandle } from './SearchTextBox';

dayjs.extend(utc);
dayjs.extend(timezone);

const EMPTY_HEATMAP: HeatmapData = { weekdayTod: [], weekdayMonth: [], hourDow: [], hourMonth: [], calendar: [], years: [] };

const SearchPage = () => {
    const dispatch = useAppDispatch();
    const navigate = useNavigate();
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

    // Reset everything (text, filters, image refs, drag blobs) — keep only device.
    const handleClearAll = useCallback(() => {
        textQueryRef.current = '';
        searchTextBoxRef.current?.setText('');
        lastParsedRef.current = {};
        setDragBlobUrls((prev) => { prev.forEach((u) => URL.revokeObjectURL(u)); return []; });
        setSearchParams(() => {
            const p = new URLSearchParams();
            if (device) p.set('device', device);
            return p;
        });
    }, [device, setSearchParams]);

    // Quick back to the previous search/result state (prior URL params).
    const handleBack = useCallback(() => navigate(-1), [navigate]);

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

    const [searchHeatmap, setSearchHeatmap] = React.useState<HeatmapData>(EMPTY_HEATMAP);

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
            const { vbsLog, dres } = store.getState();
            const log = vbsLog.enabled
                ? { evaluationId: dres.evaluationId, taskName: dres.currentTask?.name ?? null }
                : undefined;
            const options = (imageRefs.length || imageBlobs.length || log)
                ? { imagePaths: imageRefs, imageBlobs, log }
                : undefined;
            const { segments, topLocations, topCountries, topPeople, heatmap } =
                await searchImages(device, searchQuery, sortBy, options);
            // VBS log: text query (CLIP joint embedding), image examples, and any
            // active filters. No-ops unless the logging toggle is on.
            if (searchQuery.text?.trim()) {
                logEvent('text', 'jointEmbedding', searchQuery.text.trim());
            }
            if (imageRefs.length || imageBlobs.length) {
                logEvent('image', 'globalFeatures', imageRefs.join(';') || `${imageBlobs.length} image(s)`);
            }
            const FILTER_FIELDS: [keyof SearchQuery, string][] = [
                ['countries', 'country'], ['locationIds', 'location'], ['peopleIds', 'people'],
                ['years', 'year'], ['months', 'month'], ['dayOfWeeks', 'dow'], ['timeOfDays', 'tod'],
            ];
            const filters = FILTER_FIELDS
                .filter(([k]) => (searchQuery[k] as unknown[] | undefined)?.length)
                .map(([k, label]) => `${label}=${(searchQuery[k] as unknown[]).join(',')}`);
            if (filters.length) logEvent('filter', 'metadata', filters.join(' '));
            dispatch(setLoading(false));
            setPage(1);
            setDeleted([]); // fresh results — drop stale hidden paths from prior search
            setSearchSummaryData({ topLocations, topCountries, topPeople });
            setSearchHeatmap(heatmap ?? EMPTY_HEATMAP);
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

    const images = useMemo(() => results.flat(), [results]);

    const {
        renderFilterOptions,
        renderHeatmap,
        renderClearButton,
        nothingIsSelected,
    } = TemporalFiltersHook({
        heatmap: searchHeatmap,
    });

    const resultSummary = useMemo(() => {
        if (!images.length) return null;
        // Single numeric pass to find extremes; dayjs only on the two endpoints
        // (parsing 1000 dayjs objects per render was a needless cost).
        let minImg = images[0];
        let maxImg = images[0];
        let minMs = Infinity;
        let maxMs = -Infinity;
        for (const img of images) {
            const ms = Date.parse(img.timestamp);
            if (ms < minMs) { minMs = ms; minImg = img; }
            if (ms > maxMs) { maxMs = ms; maxImg = img; }
        }
        const earliest = dayjs.utc(minImg.timestamp);
        const latest = dayjs.utc(maxImg.timestamp);
        const sameDay =
            earliest.format('YYYY-MM-DD') === latest.format('YYYY-MM-DD');
        const dateRange = sameDay
            ? earliest.tz(minImg.timezone || 'UTC').format('D MMM YYYY')
            : `${earliest.tz(minImg.timezone || 'UTC').format('D MMM YYYY')} – ${latest.tz(maxImg.timezone || 'UTC').format('D MMM YYYY')}`;

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

    const deleteRow = useCallback(
        (imagePaths: string[]) => {
            // Hide immediately; roll back if the request fails.
            setDeleted((prev) => [...prev, ...imagePaths]);
            deleteImages(device, imagePaths).catch(() => {
                const restore = new Set(imagePaths);
                setDeleted((prev) => prev.filter((p) => !restore.has(p)));
                dispatch(
                    showNotification({
                        message: 'Delete failed — restored images',
                        type: 'error',
                    })
                );
            });
        },
        [device, dispatch]
    );

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

    const currentPageResults = useMemo(
        () => results?.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE) || [],
        [results, page]
    );

    const currentPageImages = useMemo(
        () =>
            (images?.slice((page - 1) * PAGE_SIZE * 2, page * PAGE_SIZE * 2) || []).filter(
                (img) => !deleted.includes(img.imagePath)
            ),
        [images, page, deleted]
    );

    // Memoize the heavy mapped lists so unrelated re-renders (e.g. opening or
    // closing a filter accordion, which flips `filterShown`) reuse the same
    // element refs and React bails out of reconciling the grid.
    const resultEventItems = useMemo(
        () =>
            currentPageResults.map((segment, index) => (
                <LifelogEvent
                    key={index}
                    segment={segment}
                    onChange={() => mutate()}
                    deleteRow={deleteRow}
                    fullTime
                />
            )),
        [currentPageResults, deleteRow, mutate]
    );

    const imageGridItems = useMemo(
        () =>
            currentPageImages?.map((image) => {
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
            }),
        [
            currentPageImages,
            deleted,
            dresSelectedImages,
            isDresSelecting,
            isSelecting,
            selectedImages,
            dispatch,
        ]
    );

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
                <Stack direction="row" alignItems="center" spacing={0.5}>
                    <Tooltip title="Back to previous results">
                        <IconButton size="small" onClick={handleBack} sx={{ p: 0.25 }}>
                            <ArrowBackRounded fontSize="small" />
                        </IconButton>
                    </Tooltip>
                    <Typography
                        variant="h6"
                        color="primary"
                        fontWeight="bold"
                    >
                        Search
                    </Typography>
                </Stack>
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
                    slotProps={{ transition: { unmountOnExit: false } }}
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
                    slotProps={{ transition: { unmountOnExit: false } }}
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
                    slotProps={{ transition: { unmountOnExit: false } }}
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
                        variant="outlined"
                        color="inherit"
                        startIcon={<ClearAllRounded />}
                        sx={{ textTransform: 'none' }}
                        onClick={handleClearAll}
                    >
                        Clear All
                    </Button>
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
                        {isLoading ? (
                            <Stack direction="row" spacing={1}>
                                <ResultSummaryBarSkeleton />
                            </Stack>
                        ) : resultSummary ? (
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
                    viewMode === 'events' ? (
                        <Stack
                            direction="row"
                            spacing={2}
                            sx={{ width: '100%' }}
                            flexWrap="wrap"
                            useFlexGap
                        >
                            {Array.from({ length: 4 }).map((_, i) => (
                                <Box key={i} sx={{ flex: '1 1 340px', minWidth: 300 }}>
                                    <LifelogEventSkeleton />
                                </Box>
                            ))}
                        </Stack>
                    ) : (
                        <Stack
                            spacing={1}
                            sx={{ flexWrap: 'wrap' }}
                            direction="row"
                            useFlexGap
                        >
                            {Array.from({ length: PAGE_SIZE * 2 }).map((_, i) => (
                                <Skeleton
                                    key={i}
                                    variant="rounded"
                                    width={150}
                                    height={200}
                                    sx={{ borderRadius: '10px' }}
                                />
                            ))}
                        </Stack>
                    )
                ) : viewMode === 'events' ? (
                    <>
                        <Stack
                            direction="row"
                            spacing={2}
                            sx={{ width: '100%' }}
                            flexWrap="wrap"
                            useFlexGap
                        >
                            {resultEventItems}
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
                                    logEvent('browsing', 'rankedList', `page ${page}`);
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
                            {imageGridItems}
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
                                    logEvent('browsing', 'rankedList', `page ${page}`);
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

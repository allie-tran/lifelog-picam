import { AddAPhotoRounded, CloseRounded } from '@mui/icons-material';
import { Box, IconButton, InputAdornment, Stack, TextField } from '@mui/material';
import { parseQueryFilters } from 'apis/browsing';
import ImageDropSearch from 'components/search/ImageDropSearch';
import React, { useEffect, useImperativeHandle, useRef, useState } from 'react';
import { SearchQuery } from '@utils/types';
import { THUMBNAIL_HOST_URL } from 'constants/urls';

export type SearchTextBoxHandle = { setText: (t: string) => void };

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

export default SearchTextBox;

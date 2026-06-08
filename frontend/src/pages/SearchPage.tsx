import {
    AddAPhotoRounded,
    ArrowDropDownRounded,
    DeleteRounded,
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
    Typography,
    styled
} from '@mui/material';
import {
    deleteImages,
    searchImages,
} from 'apis/browsing';
import DRESSettings from 'components/DRESSettings';
import { FaceFiltersHook } from 'components/FaceFilters';
import ImageDropSearch from 'components/ImageDropSearch';
import ImageWithDate from 'components/ImageWithDate';
import LifelogEvent from 'components/LifelogEvent';
import { LocationFiltersHook } from 'components/LocationFilters';
import { TemporalFiltersHook } from 'components/TemporalFilters';
import React, { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';
import { setDeviceId } from 'reducers/auth';
import { setLoading } from 'reducers/feedback';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import { setSearchQuery } from 'reducers/search';
import { setZoomedImage } from 'reducers/zoomedImage';
import useSWR from 'swr';
import '../App.css';
import { ImageZoom } from '../components/ImageZoom';
import DeviceSelect from './DeviceSelect';

const PAGE_SIZE = 20;

const SearchPage = () => {
    const dispatch = useAppDispatch();
    const [searchParams, _] = useSearchParams();
    const device = searchParams.get('device');
    const deviceId = useAppSelector((state) => state.auth.deviceId) || '';
    const searchQuery = useAppSelector((state) => state.search.query);

    useEffect(() => {
        if (device) dispatch(setDeviceId(device));
    }, [device]);

    // View Settings
    const [sortBy, setSortBy] = useState<'time' | 'relevance'>('relevance');
    const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
    const [viewMode, setViewMode] = useState<'images' | 'events'>('images');
    const [page, setPage] = useState(1);

    // Search Settings
    const [textQuery, setTextQuery] = useState('');
    const [useImageInput, setUseImageInput] = useState<boolean>(false);
    const [filterShown, setFilterShown] = useState<
        'temporal' | 'location' | 'faces' | 'dres' | null
    >(null);

    const {
        renderFilterOptions,
        renderHeatmap,
        renderClearButton,
        nothingIsSelected,
    } = TemporalFiltersHook();
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

    // Endpoints
    const {
        data: searchEvents,
        isLoading,
        mutate,
    } = useSWR(
        ['search', deviceId, sortBy, searchQuery],
        () =>
            searchImages(deviceId, searchQuery, sortBy).then((res) => {
                dispatch(setLoading(false));
                setPage(1);
                if (sortBy === 'relevance') {
                    setSortOrder('desc');
                    return res.slice().reverse();
                } else {
                    setSortOrder('asc');
                }
                return res;
            }),
        { revalidateOnFocus: false }
    );

    const results = useMemo(() => {
        if (!searchEvents) return [];
        if (sortOrder == 'desc') {
            return searchEvents.slice().reverse();
        }
        return searchEvents;
    }, [searchEvents, sortOrder]);

    const images = useMemo(() => {
        if (results.length !== 0) {
            return results.reduce((acc, segment) => {
                return [...acc, ...segment];
            });
        }
        return [];
    }, [results]);

    const [deleted, setDeleted] = useState<string[]>([]);

    const deleteRow = (imagePaths: string[]) => {
        dispatch(setLoading(true));
        deleteImages(deviceId, imagePaths).then(() => {
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
                <DeviceSelect />
                <Typography variant="caption">
                    Type in a prompt in natural language
                </Typography>
                {/* <DeviceSelect /> */}
                <TextField
                    variant="outlined"
                    multiline
                    rows={3}
                    value={textQuery}
                    onChange={(e) => setTextQuery(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                            e.preventDefault();
                            dispatch(setSearchQuery({ text: textQuery }));
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
                <StyledAccordion
                    square
                    elevation={0}
                    expanded={filterShown === 'dres'}
                    onChange={() =>
                        setFilterShown((prev) =>
                            prev === 'dres' ? null : 'dres'
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
                                        filterShown === 'dres'
                                            ? 'rotate(180deg)'
                                            : 'rotate(0deg)',
                                }}
                            />
                            DRES Competition
                        </Typography>
                    </AccordionSummary>
                    <AccordionDetails sx={{ padding: 0 }}>
                        <DRESSettings />
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
                        onClick={
                            () => dispatch(setSearchQuery({ text: textQuery }))
                        }
                    >
                        Search
                    </Button>
                </Stack>
            </Drawer>

            <Box sx={{ paddingLeft: '325px', transform: 'translateY(-80px)' }}>
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
                        <Stack direction="row" spacing={1}>
                            <Typography
                                variant="h6"
                                color="text.primary"
                                paddingLeft={1}
                                sx={{ width: 128 }}
                            >
                                Result Summary
                            </Typography>
                            <Typography
                                variant="body2"
                                color="text.secondary"
                                paddingLeft={1}
                            >
                                Coverage: 21/04/2024 – 07/09/2024 (5 months 16
                                days) <br />
                                # Events: 1,225 <br />
                                # Photos: 48,209 <br />
                            </Typography>
                        </Stack>
                        {filterShown === 'temporal' && renderHeatmap()}
                        {filterShown === 'location' && renderMap()}
                        {filterShown === 'faces' && renderFaceExplorer()}
                    </Stack>
                </Stack>
                <Stack
                    direction="row"
                    justifyContent="flex-end"
                    spacing={4}
                    sx={{ marginY: 0.5, paddingRight: 2 }}
                >
                    <SimpleToggleButtonGroup
                        description="View by:"
                        value={viewMode}
                        onChange={(value) =>
                            setViewMode(value as 'events' | 'images')
                        }
                        values={[
                            { label: 'Events', value: 'events' },
                            { label: 'Images', value: 'images' },
                        ]}
                    />
                    <SimpleToggleButtonGroup
                        description="Sort by:"
                        value={sortBy}
                        onChange={(value) =>
                            setSortBy(value as 'time' | 'relevance')
                        }
                        values={[
                            { label: 'Relevance', value: 'relevance' },
                            { label: 'Time', value: 'time' },
                        ]}
                    />
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
                            {currentPageResults.map(
                                (segment, index) => (
                                    <LifelogEvent
                                        key={index}
                                        segment={segment}
                                        onChange={() => mutate()}
                                        deleteRow={deleteRow}
                                        fullTime
                                    />
                                )
                            )}
                        </Stack>
                        {page > 0 && (
                            <Pagination
                                page={page}
                                count={Math.ceil(
                                    results.length / PAGE_SIZE
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

const SimpleToggleButtonGroup = ({
    description,
    values,
    value,
    onChange,
}: {
    description: string;
    values: { label: string; value: string }[];
    value: string;
    onChange: (value: string) => void;
}) => {
    return (
        <Stack direction="row" alignItems="center" spacing={1}>
            <Typography variant="caption" color="text.secondary">
                {description}
            </Typography>
            <Stack direction="row" spacing={0.5} alignItems="center">
                {values.map((option, index) => (
                    <React.Fragment key={option.value}>
                        <Typography
                            key={option.value}
                            variant="caption"
                            color={
                                value === option.value
                                    ? 'text.primary'
                                    : 'grey.400'
                            }
                            sx={{
                                cursor: 'pointer',
                                textDecoration:
                                    value === option.value
                                        ? 'underline'
                                        : 'none',
                                fontWeight:
                                    value === option.value ? 'bold' : 'normal',
                            }}
                            onClick={() => onChange(option.value)}
                        >
                            {option.label}
                        </Typography>
                        {index < values.length - 1 && (
                            <Typography
                                variant="caption"
                                color="text.secondary"
                            >
                                |
                            </Typography>
                        )}
                    </React.Fragment>
                ))}
            </Stack>
        </Stack>
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

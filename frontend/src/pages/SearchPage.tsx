import {
    Box,
    Button,
    Container,
    Divider,
    Drawer,
    LinearProgress,
    Pagination,
    Paper,
    Stack,
    styled,
    Tab,
    Tabs,
    ToggleButton,
    ToggleButtonGroup,
    Typography,
} from '@mui/material';
import { ImageObject } from '@utils/types';
import { deleteImage, searchImages, similarImages, similarImagesPost } from 'apis/browsing';
import ImageIdSearch from 'components/ImageIdSearch';
import LifelogEvent from 'components/LifelogEvent';
import SearchBar from 'components/SearchBar';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { setLoading } from 'reducers/feedback';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import useSWR from 'swr';
import '../App.css';
import { ImageZoom } from '../components/ImageZoom';
import DeviceSelect from './DeviceSelect';
import ImageDropSearch from 'components/ImageDropSearch';
import ImageWithDate from 'components/ImageWithDate';
import { setZoomedImage } from 'reducers/zoomedImage';
import { DeleteRounded } from '@mui/icons-material';

const PAGE_SIZE = 10;

const SearchPage = () => {
    const dispatch = useAppDispatch();
    const [searchParams, _] = useSearchParams();
    const query = searchParams.get('query') || '';
    const mode = searchParams.get('mode') || 'text';

    const deviceId = useAppSelector((state) => state.auth.deviceId) || '';
    const [sortBy, setSortBy] = useState<'time' | 'relevance'>('relevance');
    const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
    const [viewMode, setViewMode] = useState<'images' | 'events'>('events');
    const [tempMode, setTempMode] = useState(mode);
    const [page, setPage] = useState(1);

    const {
        data: searchEvents,
        isLoading,
        mutate,
    } = useSWR(
        ['search', query, sortBy],
        mode === 'text'
            ? () =>
                  searchImages(deviceId, query, sortBy).then((res) => {
                      dispatch(setLoading(false));
                      setPage(1);
                      if (sortBy === 'relevance') {
                          setSortOrder('desc');
                          return res.slice().reverse();
                      } else {
                          setSortOrder('asc');
                      }
                      return res;
                  })
            : null,
        {
            revalidateOnFocus: false,
        }
    );

    const { data: similar, isLoading: isSimilarLoading } = useSWR<
        ImageObject[]
    >(
        ['similar-images', searchParams.get('query')],
        mode === 'id'
            ? () =>
                  similarImages(deviceId, searchParams.get('query') || '').then(
                      (res) => {
                          dispatch(setLoading(false));
                          setPage(1);
                          setViewMode('images');
                          return res as ImageObject[];
                      }
                  )
            : mode === 'similar'
              ? () =>
                    similarImagesPost(
                        deviceId,
                        searchParams.get('query') || ''
                    ).then((res) => {
                        dispatch(setLoading(false));
                        setPage(1);
                        setViewMode('images');
                        return res as ImageObject[];
                    })
              : null,
        {
            revalidateOnFocus: false,
        }
    );

    const results = useMemo(() => {
        if (!searchEvents) return [];
        if (sortOrder == 'desc') {
            return searchEvents.slice().reverse();
        }
        return searchEvents;
    }, [searchEvents, sortOrder]);

    const images = useMemo(() => {
        if (mode === 'text') {
            if (results.length !== 0) {
                return results.reduce((acc, segment) => {
                    return [...acc, ...segment];
                });
            }
            return [];
        } else {
            return similar || [];
        }
    }, [results, similar, mode]);

    const [deleted, setDeleted] = useState<string[]>([]);

    const deleteRow = (imagePaths: string[]) => {
        dispatch(setLoading(true));
        Promise.all(imagePaths.map((path) => deleteImage(deviceId, path))).then(
            () => {
                mutate().then(() => dispatch(setLoading(false)));
            }
        );
    };

    useEffect(() => {
        setTempMode(mode);
    }, [mode]);

    const currentPageResults =
        results?.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE) || [];

    const currentPageImages =
        images?.slice((page - 1) * PAGE_SIZE * 2, page * PAGE_SIZE * 2) || [];

    const deletePage = () => {
        const imagePaths = currentPageImages.map((img) => img.imagePath);
        deleteRow(imagePaths);
    };

    return (
        <>
            <Drawer anchor="right" open={true} variant="permanent">
                <Stack spacing={2} padding={2} width={200}>
                    <Typography variant="subtitle1" fontWeight="bold">
                        Sort By
                    </Typography>
                    <ToggleButtonGroup
                        color="primary"
                        value={sortBy}
                        exclusive
                        onChange={(_, value) => setSortBy(value)}
                        sx={{ width: '100%' }}
                    >
                        <FullWidthToggleButton value="relevance">
                            Relevance
                        </FullWidthToggleButton>
                        <FullWidthToggleButton value="time">
                            Time
                        </FullWidthToggleButton>
                    </ToggleButtonGroup>
                    <Typography variant="subtitle1" fontWeight="bold">
                        Order
                    </Typography>
                    <Button
                        variant="outlined"
                        color="primary"
                        sx={{ textTransform: 'none' }}
                        onClick={() =>
                            setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')
                        }
                    >
                        {sortOrder === 'asc' ? 'Ascending' : 'Descending'}
                        <svg
                            width="14"
                            height="14"
                            fill="currentColor"
                            viewBox="0 0 24 24"
                            style={{
                                transform:
                                    sortOrder === 'asc'
                                        ? 'rotate(180deg)'
                                        : 'none',
                                marginLeft: 8,
                            }}
                        >
                            <path d="M7 10l5 5 5-5z" />
                        </svg>
                    </Button>
                    <Typography variant="subtitle1" fontWeight="bold">
                        View Mode
                    </Typography>
                    <ToggleButtonGroup
                        color="primary"
                        value={viewMode}
                        exclusive
                        onChange={(_, value) => setViewMode(value)}
                    >
                        <FullWidthToggleButton value="events">
                            Events
                        </FullWidthToggleButton>
                        <FullWidthToggleButton value="images">
                            Images
                        </FullWidthToggleButton>
                    </ToggleButtonGroup>
                </Stack>
            </Drawer>
            <Box sx={{ paddingRight: '200px' }}>
                <Box id="app" sx={{ width: '100%' }} />
                <Typography
                    variant="h4"
                    marginTop={4}
                    marginBottom={2}
                    color="primary"
                    fontWeight="bold"
                >
                    Search
                </Typography>
                <Box
                    sx={{
                        borderBottom: 1,
                        borderColor: 'divider',
                        marginBottom: 2,
                    }}
                >
                    <Tabs
                        value={tempMode}
                        onChange={(_, value) => setTempMode(value)}
                    >
                        <Tab label="Activity/Text" value="text" />
                        <Tab label="Image ID" value="id" />
                        <Tab label="Visual Search" value="similar" />
                    </Tabs>
                </Box>
                <Paper
                    component={Stack}
                    direction="row"
                    justifyContent="center"
                    alignItems="center"
                    spacing={2}
                    sx={{
                        borderRadius: 2,
                        width: '100%',
                        justifySelf: 'center',
                        marginX: 'auto',
                        marginY: 4,
                        px: 2,
                        py: 1,
                        alignItems: 'flex-start',
                    }}
                >
                    <DeviceSelect />
                    <SearchBar visible={tempMode === 'text'} />
                    <ImageIdSearch visible={tempMode === 'id'} />
                    <ImageDropSearch visible={tempMode === 'similar'} />
                </Paper>
                {isLoading || isSimilarLoading ? (
                    <LinearProgress sx={{ marginBottom: 2 }} />
                ) : viewMode === 'events' ? (
                    <>
                        <Typography>
                            Showing results for: "{searchParams.get('query')}"
                        </Typography>
                        <Divider sx={{ marginY: 2 }} />
                        {viewMode === 'events' && (
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
                            </>
                        )}
                    </>
                ) : (
                    <>
                        <Button
                            color="error"
                            onClick={deletePage}
                            sx={{ textTransform: 'none', marginBottom: 2 }}
                        >
                            <DeleteRounded sx={{ marginRight: 1 }} />
                            Delete All on This Page
                        </Button>
                        <Stack
                            spacing={2}
                            sx={{ flexWrap: 'wrap' }}
                            direction="row"
                            useFlexGap
                            justifyContent="center"
                        >
                            {currentPageImages?.map((image) =>
                                deleted.includes(image.imagePath) ? null : (
                                    <ImageWithDate
                                        fontSize={'12px'}
                                        height={'250px'}
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
                                    />
                                )
                            )}
                        </Stack>
                        <Pagination
                            page={page}
                            count={Math.ceil(images.length / (PAGE_SIZE * 2))}
                            color="primary"
                            sx={{
                                display: 'flex',
                                justifyContent: 'center',
                                marginY: 4,
                            }}
                            onChange={(_, page) => {
                                setPage(page);
                                const element = document.getElementById('app');
                                element?.scrollIntoView({
                                    behavior: 'smooth',
                                });
                            }}
                        />
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

const FullWidthToggleButton = styled(ToggleButton)(({ theme }) => ({
    width: '100%',
    textTransform: 'none',
}));

export default SearchPage;

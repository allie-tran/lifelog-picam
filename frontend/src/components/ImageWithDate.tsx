import {
    DeleteRounded,
    EditRounded,
    SendRounded,
    TimerRounded,
    VideocamRounded,
} from '@mui/icons-material';
import { Box, Button, CircularProgress, Stack, Tooltip, Typography } from '@mui/material';
import { THUMBNAIL_HOST_URL } from '../constants/urls';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';
import { deleteImage, deleteImages, getContextImages } from 'apis/browsing';
import { submitImage } from 'apis/dres';
import { ImageObject, ResultSegment } from '@utils/types';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import { addSubmittedImages } from 'reducers/dres';
import { useSearchParams } from 'react-router';
import { useEffect, useState } from 'react';
import { showNotification } from 'reducers/feedback';
import Annotator from './Annotator';
import ModalWithCloseButton from './ModalWithCloseButton';
import LifelogEvent from './LifelogEvent';
import { parseErrorResponse } from '@utils/misc';

dayjs.extend(utc);
dayjs.extend(timezone);

const ImageWithDate = ({
    image,
    onClick,
    extra,
    onDelete,
    height = '220px',
    fontSize,
    disableDelete = false,
    timeOnly = false,
    device: deviceProp,
}: {
    image: ImageObject;
    onClick?: () => void;
    extra?: React.ReactNode;
    onDelete?: (image: string) => void;
    height?: number | string;
    fontSize?: number | string;
    disableDelete?: boolean;
    timeOnly?: boolean;
    device?: string;
}) => {
    const [deleted, setDeleted] = useState(false);
    const [showAnnotator, setShowAnnotator] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const dispatch = useAppDispatch();
    const [searchParams] = useSearchParams();
    const device = deviceProp ?? searchParams.get('device') ?? '';
    const { evaluationId, sessionId, currentTask, submittedImages } = useAppSelector((state) => state.dres);
    const isDresSubmitted = submittedImages.includes(image.imagePath);
    const imageUrl = image.thumbnail
        ? `${THUMBNAIL_HOST_URL}/${device}/${image.thumbnail}`
        : '';
    const formattedDate = timeOnly
        ? dayjs.utc(image.timestamp).tz(image.timezone || 'UTC').format('HH:mm z')
        : dayjs.utc(image.timestamp).tz(image.timezone || 'UTC').format('dd DD MMM YYYY HH:mm z');

    const handleDelete = async () => {
        setDeleted(true);
        await deleteImage(device, image.imagePath);
        onDelete && onDelete(image.imagePath);
    };

    const [context, setContext] = useState<ResultSegment[]>([]);
    const [deletedIndexes, setDeletedIndexes] = useState<number[]>([]);

    useEffect(() => {
        return () => {
            setDeleted(false);
        };
    }, [image.imagePath]);

    const getContext = async () => {
        try {
            const res = await getContextImages(device, image.imagePath);
            setContext(res);
            setDeletedIndexes([]);
        } catch (err) {
            console.error('Failed to fetch context images:', err);
        }
    };

    const handleDRESSubmit = async () => {
        if (!evaluationId || !sessionId) return;
        setSubmitting(true);
        try {
            const result = await submitImage({ image: image.imagePath, evaluationId, sessionId });
            dispatch(addSubmittedImages([image.imagePath]));
            dispatch(showNotification({
                message: `DRES: ${result.verdict} — ${result.message}`,
                type: result.severity,
            }));
        } catch (err: any) {
            const reason = err.data?.description || parseErrorResponse(err) || 'Unknown error';
            dispatch(showNotification({ message: reason, type: 'error' }));
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <Box
            sx={{
                marginBottom: '20px',
                height: height,
                position: 'relative',
                width: 'auto',
                opacity: deleted ? 0 : isDresSubmitted ? 0.55 : 1,
                outline: isDresSubmitted ? '2px solid #a5d6a7' : 'none',
                borderRadius: '10px',
                transition: 'all .2s',
                visibility: deleted ? 'hidden' : 'visible',
            }}
        >
            {imageUrl ? (
                <Box
                    component="img"
                    sx={{
                        position: 'relative',
                        cursor: onClick ? 'pointer' : 'default',
                        height: 'calc(100% - 24px)',
                        width: 'auto',
                        borderRadius: '8px',
                        backgroundColor: '#ccc',
                        minWidth: '100px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                    }}
                    onClick={onClick}
                    src={imageUrl}
                    alt={image.imagePath}
                />
            ) : (
                <Box
                    sx={{
                        position: 'relative',
                        height: 'calc(100% - 24px)',
                        width: 'auto',
                        aspectRatio: '9 / 16',
                        borderRadius: '8px',
                        backgroundColor: '#ccc',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: '#666',
                    }}
                >
                    Not processed
                </Box>
            )}
            {image.new && (
                <Typography
                    variant="caption"
                    sx={{
                        position: 'absolute',
                        top: 8,
                        right: 8,
                        color: 'white',
                        backgroundColor: 'red',
                        px: 0.5,
                        borderRadius: '4px',
                    }}
                >
                    New
                </Typography>
            )}
            <VideocamRounded
                sx={{
                    position: 'absolute',
                    top: 8,
                    left: 8,
                    color: 'white',
                    backgroundColor: 'rgba(0, 0, 0, 0.6)',
                    borderRadius: '50%',
                    padding: '4px',
                    display: image.isVideo ? 'block' : 'none',
                }}
                fontSize="medium"
                titleAccess="Video"
            />
            <Stack
                direction="row"
                spacing={1}
                sx={{
                    px: 0.5,
                }}
            >
                <Typography
                    sx={{
                        fontSize: fontSize || '14px',
                        userSelect: 'none',
                        backgroundColor: 'rgba(0, 0, 0, 0.6)',
                        color: 'white',
                        px: 1,
                        borderRadius: '4px',
                    }}
                >
                    {formattedDate}
                </Typography>
            </Stack>
            <Stack direction="row" spacing={0} alignItems="center">
                {!disableDelete && (
                    <Button
                        color="error"
                        size="small"
                        sx={{
                            fontSize: '12px',
                            minWidth: 24,
                        }}
                        onClick={handleDelete}
                    >
                        <DeleteRounded />
                    </Button>
                )}
                <Button
                    color="primary"
                    size="small"
                    sx={{
                        fontSize: '12px',
                        minWidth: 24,
                    }}
                    onClick={() => setShowAnnotator((prev) => !prev)}
                >
                    <EditRounded />
                </Button>
                <Button
                    color="secondary"
                    size="small"
                    sx={{
                        fontSize: '12px',
                        minWidth: 24,
                    }}
                    onClick={getContext}
                >
                    <TimerRounded />
                </Button>
                {evaluationId && sessionId && (
                    <Tooltip title={currentTask ? `Submit to: ${currentTask.name}` : 'Submit to DRES'}>
                        <span>
                            <Button
                                color="success"
                                size="small"
                                sx={{ fontSize: '12px', minWidth: 24 }}
                                onClick={handleDRESSubmit}
                                disabled={submitting}
                            >
                                {submitting
                                    ? <CircularProgress size={14} color="inherit" />
                                    : <SendRounded fontSize="small" />}
                            </Button>
                        </span>
                    </Tooltip>
                )}
                {extra}
            </Stack>
            <ModalWithCloseButton
                open={showAnnotator}
                onClose={() => setShowAnnotator(false)}
            >
                <Annotator image={image} />
            </ModalWithCloseButton>
            <ModalWithCloseButton
                open={context.length > 0}
                onClose={() => setContext([])}
            >
                {context.map((segment, index) => {
                    const deletedInSegment = deletedIndexes.includes(index);
                    if (deletedInSegment) {
                        return null;
                    }
                    return (
                        <LifelogEvent
                            key={index}
                            segment={segment.images}
                            onChange={() => {}}
                            deleteRow={() => {
                                deleteImages(
                                    device,
                                    segment.images.map((img) => img.imagePath)
                                ).then(() => {
                                    setDeletedIndexes((prev) => [
                                        ...prev,
                                        index,
                                    ]);
                                });
                            }}
                        />
                    );
                })}
            </ModalWithCloseButton>
        </Box>
    );
};

export default ImageWithDate;

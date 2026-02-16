import { ImageSearchRounded } from '@mui/icons-material';
import { Box, Button, Stack, Typography } from '@mui/material';
import React, { useState } from 'react';
import { FileUploader } from 'react-drag-drop-files';
import { useNavigate, useSearchParams } from 'react-router';
import '../App.css';

const ImageDropSearch = ({ visible = true }: { visible?: boolean }) => {
    const [searchParams, _] = useSearchParams();
    const navigate = useNavigate();
    const [file, setFile] = useState<File | null>(null);

    const handleChange = (file: File | File[]) => {
        if (file instanceof File) {
            setFile(file);
        } else {
            setFile(file[0]);
        }
    };

    const onSearch = (blobUrl: string) => {
        navigate(`/search?mode=similar&&query=${encodeURIComponent(blobUrl)}`);
    };

    return (
        <Stack
            direction="row"
            spacing={2}
            alignItems="flex-start"
            sx={{ display: visible ? 'flex' : 'none', width: '100%', pt: 1 }}
        >
            <FileUploader
                name="file"
                label="Upload an image to find similar ones"
                multiple={false}
                handleChange={handleChange}
                types={['JPG', 'PNG', 'GIF', 'JPEG', 'BMP']}
                classes="file-uploader"
            >
                <Stack
                    spacing={1}
                    justifyContent="center"
                    alignItems="center"
                    sx={{
                        padding: 2,
                        border: '1px dashed',
                        borderColor: 'rgb(220, 220, 220, 0.5)',
                        borderRadius: 2,
                        cursor: 'pointer',
                        width: '100%',
                        '&:hover': {
                            borderColor: 'primary.main',
                        },
                    }}
                >
                    <ImageSearchRounded sx={{ fontSize: 32 }} />
                    <Typography>
                        Click or drag an image here to search for similar ones
                    </Typography>
                    {file && (
                        <>
                            <img
                                src={URL.createObjectURL(file)}
                                alt="Uploaded"
                                style={{
                                    maxWidth: '200px',
                                    maxHeight: '200px',
                                    objectFit: 'contain',
                                }}
                            />
                        </>
                    )}
                </Stack>
            </FileUploader>
            <Stack sx={{ paddingTop: "1px" }} spacing={2} alignItems="center">
                <Button
                    variant="outlined"
                    onClick={() => {
                        if (file) {
                            const blobUrl = URL.createObjectURL(file);
                            onSearch(blobUrl);
                        }
                    }}
                    sx={{
                        padding: 1.5,
                        outline: '2px solid',
                        minWidth: '100px',
                    }}
                >
                    <strong>Lookup</strong>
                </Button>
                {file && (
                <Button
                    onClick={(e) => {
                        e.stopPropagation();
                        setFile(null);
                    }}
                    color="error"
                    sx={{
                        textTransform: 'none',
                        paddingX: 3,
                    }}
                >
                    Clear
                </Button>
                )}
            </Stack>
        </Stack>
    );
};
export default ImageDropSearch;

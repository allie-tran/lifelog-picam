import CloseIcon from '@mui/icons-material/Close';
import { Button, Modal, Stack } from '@mui/material';
import React from 'react';

const ModalWithCloseButton = ({
    children,
    open,
    onClose,
    fitContent = false,
    sx,
}: {
    children: React.ReactNode;
    onClose: () => void;
    open: boolean;
    fitContent?: boolean;
    sx?: React.CSSProperties;
}) => {
    return (
        <Modal
            open={open}
            onClose={onClose}
            sx={{
                zIndex: 1300, // Ensure it appears above other content
                ...sx,
            }}
        >
            <Stack
                sx={{
                    position: 'absolute',
                    top: '50%',
                    left: '50%',
                    transform: 'translate(-50%, -50%)',
                    bgcolor: 'background.paper',
                    boxShadow: 24,
                    p: { xs: 2, sm: 4 },
                    height: fitContent ? 'fit-content' : '90dvh',
                    width: fitContent ? 'fit-content' : '90dvw',
                    // fit-content can still overflow a phone once its children
                    // have an intrinsic width, so cap it against the viewport.
                    maxWidth: '95dvw',
                    maxHeight: '90dvh',
                    overflowY: 'auto',
                    borderRadius: '8px',
                    alignItems: 'center',
                }}
            >
                <Button
                    onClick={onClose}
                    sx={{ position: 'absolute', top: 8, right: 8 }}
                >
                    <CloseIcon />
                </Button>
                {children}
            </Stack>
        </Modal>
    );
};

export default ModalWithCloseButton;

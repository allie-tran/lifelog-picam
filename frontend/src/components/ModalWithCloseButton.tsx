import CloseIcon from '@mui/icons-material/Close';
import { Box, Button, Modal, Stack } from '@mui/material';
import React from 'react';

const ModalWithCloseButton = ({
    children,
    open,
    onClose,
}: {
    children: React.ReactNode;
    onClose: () => void;
    open: boolean;
}) => {
    return (
        <Modal open={open} onClose={onClose}>
            <Stack
                sx={{
                    position: 'absolute',
                    top: '50%',
                    left: '50%',
                    transform: 'translate(-50%, -50%)',
                    bgcolor: 'background.paper',
                    boxShadow: 24,
                    p: 4,
                    height: '90dvh',
                    width: '90dvw',
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

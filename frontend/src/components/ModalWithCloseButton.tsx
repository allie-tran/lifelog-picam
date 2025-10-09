import CloseIcon from '@mui/icons-material/Close';
import {
    Box,
    Button,
    Modal
} from '@mui/material';
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
            <Box
                sx={{
                    position: 'absolute',
                    top: '50%',
                    left: '50%',
                    transform: 'translate(-50%, -50%)',
                    bgcolor: 'background.paper',
                    boxShadow: 24,
                    p: 4,
                    maxHeight: '80vh',
                    maxWidth: '80vw',
                    overflowY: 'auto',
                    borderRadius: '8px',
                }}
            >
                <Button
                    onClick={onClose}
                    sx={{ position: 'absolute', top: 8, right: 8 }}
                >
                    <CloseIcon />
                </Button>
                {children}
            </Box>
        </Modal>
    );
};

export default ModalWithCloseButton;

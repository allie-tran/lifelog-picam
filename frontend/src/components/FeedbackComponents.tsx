import { CircularProgress, Modal, Snackbar } from '@mui/material';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';

const FeedbackComponents = () => {
    const { notification, loading } = useAppSelector((state) => state.feedback);
    const dispatch = useAppDispatch();

    return (
        <>
            <Snackbar
                open={notification !== null}
                autoHideDuration={6000}
                onClose={() => dispatch({ type: 'feedback/hideNotification' })}
                message={notification ? notification.message : ''}
                anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
            />
            <Modal
                open={loading}
                aria-labelledby="loading-modal"
                aria-describedby="loading-modal-description"
                sx={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                }}
            >
                <div id="loading-modal-description" style={{ color: 'white' }}>
                    <CircularProgress size="3rem" />
                </div>
            </Modal>
        </>
    );
};

export default FeedbackComponents;

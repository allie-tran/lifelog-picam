import * as faceapi from 'face-api.js';
import { useCallback, useEffect, useRef, useState } from 'react';
import Webcam from 'react-webcam';

const STEPS = [
    { key: 'front', label: 'Look Straight', icon: '👤' },
    { key: 'left', label: 'Turn Left', icon: '⬅️' },
    { key: 'right', label: 'Turn Right', icon: '➡️' },
    // { key: 'up', label: 'Look Up', icon: '⬆️' },
    // { key: 'down', label: 'Look Down', icon: '⬇️' },
];

const useFaceEnrollmentWithPose = () => {
    const webcamRef = useRef<Webcam>(null);
    const animationFrameRef = useRef<number | null>(null);

    const [isLoaded, setIsLoaded] = useState(false);
    const [status, setStatus] = useState('Initializing AI...');
    const [isEnrolling, setIsEnrolling] = useState(false);
    const [currentStepIndex, setCurrentStepIndex] = useState(0);
    const [capturedData, setCapturedData] = useState<{
        [key: string]: { image: string; descriptor: Float32Array };
    }>({});

    // Use refs to expose latest state to the rAF loop without restarting it
    const isEnrollingRef = useRef(isEnrolling);
    const currentStepIndexRef = useRef(currentStepIndex);
    const capturedDataRef = useRef(capturedData);

    useEffect(() => {
        isEnrollingRef.current = isEnrolling;
    }, [isEnrolling]);
    useEffect(() => {
        currentStepIndexRef.current = currentStepIndex;
    }, [currentStepIndex]);
    useEffect(() => {
        capturedDataRef.current = capturedData;
    }, [capturedData]);

    useEffect(() => {
        const MODEL_URL =
            'https://justadudewhohacks.github.io/face-api.js/models';
        Promise.all([
            faceapi.nets.tinyFaceDetector.loadFromUri(MODEL_URL),
            faceapi.nets.faceLandmark68Net.loadFromUri(MODEL_URL),
            faceapi.nets.faceRecognitionNet.loadFromUri(MODEL_URL),
        ])
            .then(() => {
                setIsLoaded(true);
                setStatus('Ready for Enrollment');
            })
            .catch((err) => {
                setStatus('Error loading models');
                console.error(err);
            });
    }, []);

    const playBeep = useCallback(() => {
        const ctx = new (window.AudioContext ||
            (window as any).webkitAudioContext)();
        const oscillator = ctx.createOscillator();
        const gain = ctx.createGain();

        oscillator.connect(gain);
        gain.connect(ctx.destination);

        oscillator.type = 'sine';
        oscillator.frequency.setValueAtTime(880, ctx.currentTime); // A5
        oscillator.frequency.exponentialRampToValueAtTime(
            1200,
            ctx.currentTime + 0.08
        ); // sweep up
        gain.gain.setValueAtTime(0.3, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.2);

        oscillator.start(ctx.currentTime);
        oscillator.stop(ctx.currentTime + 0.2);
        oscillator.onended = () => ctx.close();
    }, []);

    const estimatePose = (landmarks: faceapi.FaceLandmarks68) => {
        const nose = landmarks.getNose();
        const jaw = landmarks.getJawOutline();
        const leftEye = landmarks.getLeftEye();
        const rightEye = landmarks.getRightEye();

        const noseTip = nose[6];
        const leftEyeOuter = leftEye[0];
        const rightEyeOuter = rightEye[3];

        const distLeft = Math.sqrt(
            Math.pow(noseTip.x - leftEyeOuter.x, 2) +
                Math.pow(noseTip.y - leftEyeOuter.y, 2)
        );
        const distRight = Math.sqrt(
            Math.pow(noseTip.x - rightEyeOuter.x, 2) +
                Math.pow(noseTip.y - rightEyeOuter.y, 2)
        );
        const yaw = distLeft / (distLeft + distRight) - 0.5;

        const noseBridge = nose[0];
        const chin = jaw[8];
        const totalFaceHeight = chin.y - noseBridge.y;
        const pitch = (noseTip.y - noseBridge.y) / totalFaceHeight - 0.35;

        return { yaw: yaw * 100, pitch: pitch * 100 };
    };

    const captureFrame = useCallback(
        (key: string, descriptor: Float32Array) => {
            if (!webcamRef.current) return;

            const image = webcamRef.current.getScreenshot();
            if (!image) {
                console.warn('Failed to capture image for step:', key);
                return;
            }
            // Save the captured frame
            setCapturedData((prev) => ({
                ...prev,
                [key]: { image, descriptor },
            }));

            // Advance to the next step using functional update to always get latest index
            setCurrentStepIndex((prev) => {
                const next = prev + 1;
                if (next < STEPS.length) {
                    setStatus(STEPS[next].label);
                } else {
                    setIsEnrolling(false);
                    setStatus('Enrollment Complete!');
                }
                return next;
            });
        },
        [webcamRef]
    );

    // Stores the landmark positions from the previous frame to measure motion
    const prevLandmarksRef = useRef<faceapi.Point[] | null>(null);

    const isStill = useCallback((current: faceapi.Point[]): boolean => {
        const prev = prevLandmarksRef.current;
        if (!prev) return false; // no previous frame to compare against

        // Average pixel movement across all 68 landmarks
        let totalDelta = 0;
        for (let i = 0; i < current.length; i++) {
            totalDelta += Math.hypot(
                current[i].x - prev[i].x,
                current[i].y - prev[i].y
            );
        }
        const avgDelta = totalDelta / current.length;

        // Capture only if average landmark movement is under 1.5px between frames
        return avgDelta < 1.5;
    }, []);

    // Stable detection loop — uses refs so it never needs to be recreated
    const detect = useCallback(async () => {
        if (!webcamRef.current) {
            console.warn('Webcam not available for detection');
            return;
        }
        try {
            const detection = await faceapi
                .detectSingleFace(
                    webcamRef.current.video as HTMLVideoElement,
                    new faceapi.TinyFaceDetectorOptions()
                )
                .withFaceLandmarks()
                .withFaceDescriptor();
            if (detection) {
                const pose = estimatePose(detection.landmarks);
                const currentLandmarks = detection.landmarks.positions;
                const stepIndex = currentStepIndexRef.current;

                if (isEnrollingRef.current && stepIndex < STEPS.length) {
                    if (!isStill(currentLandmarks)) {
                        console.log(
                            'Face is moving too much, waiting for stillness...'
                        );
                        prevLandmarksRef.current = currentLandmarks;
                        animationFrameRef.current =
                            requestAnimationFrame(detect);
                        return;
                    }
                    const step = STEPS[stepIndex];
                    if (!step) {
                        animationFrameRef.current =
                            requestAnimationFrame(detect);
                        return;
                    }

                    // Skip if already captured for this step
                    if (capturedDataRef.current[step.key]) {
                        animationFrameRef.current =
                            requestAnimationFrame(detect);
                        return;
                    }

                    console.log(
                        `Pose for step "${step.label}": yaw=${pose.yaw.toFixed(
                            2
                        )}, pitch=${pose.pitch.toFixed(2)}`
                    );
                    let isValid = false;
                    switch (step.key) {
                        case 'front':
                            isValid =
                                Math.abs(pose.yaw) < 5 &&
                                Math.abs(pose.pitch) < 10;
                            break;
                        case 'left':
                            isValid = pose.yaw > 7;
                            break;
                        case 'right':
                            isValid = pose.yaw < -7;
                            break;
                        case 'up':
                            isValid = pose.pitch < -2;
                            break;
                        case 'down':
                            isValid = pose.pitch > 20;
                            break;
                    }

                    if (isValid) {
                        // play a sound
                        playBeep();
                        console.log(`Capturing for step: ${step.label}`);
                        captureFrame(step.key, detection.descriptor);
                    }
                }
            }
        } catch (err) {
            console.error('Error during face detection:', err);
            animationFrameRef.current = requestAnimationFrame(detect);
            return;
        }

        animationFrameRef.current = requestAnimationFrame(detect);
    }, [
        isLoaded,
        captureFrame,
        estimatePose,
        isEnrolling,
        webcamRef,
        playBeep,
        isStill,
    ]);

    // Start the detection loop once models are loaded; never restart it
    useEffect(() => {
        if (!isLoaded) return;
        animationFrameRef.current = requestAnimationFrame(detect);
        return () => {
            if (animationFrameRef.current !== null) {
                cancelAnimationFrame(animationFrameRef.current);
            }
        };
    }, [isLoaded, detect]);

    const startEnrollment = () => {
        setCapturedData({});
        setCurrentStepIndex(0);
        setIsEnrolling(true);
        setStatus(STEPS[0].label);
    };

    return {
        webcamRef,
        isLoaded,
        status,
        isEnrolling,
        currentStepIndex,
        startEnrollment,
        done: currentStepIndex >= STEPS.length,
        capturedImages: Object.values(capturedData).map((data) => data.image),
    };
};

export default useFaceEnrollmentWithPose;

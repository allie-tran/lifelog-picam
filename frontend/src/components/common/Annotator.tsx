import { addAnnotation } from 'apis/browsing';
import { ImageObject } from '@utils/types';
import { THUMBNAIL_HOST_URL } from 'constants/urls';
import { useRef, useState, useEffect, MouseEvent } from 'react';
import { useSearchParams } from 'react-router';
import { useAppSelector } from 'reducers/hooks';

// Define the shape of our coordinate points
interface Point {
    x: number;
    y: number;
}

const Annotator = ({ image }: { image: ImageObject }) => {
    const windowWidth = window.innerWidth;
    const windowHeight = window.innerHeight;
    // Specify the HTMLCanvasElement type for the ref
    const canvasRef = useRef<HTMLCanvasElement | null>(null);
    const [points, setPoints] = useState<Point[]>([]);
    const [searchParams] = useSearchParams();
    const device = searchParams.get('device') || '';
    const user =
        useAppSelector((state) => state.auth.username) || 'unknown_user';
    const [imageUrl, setImageUrl] = useState<string>(image.thumbnail
        ? `${THUMBNAIL_HOST_URL}/${device}/${image.thumbnail}`
        : '');

    useEffect(() => {
        setImageUrl(image.thumbnail
            ? `${THUMBNAIL_HOST_URL}/${device}/${image.thumbnail}`
            : '');
    }, [image.thumbnail, device]);

    const MAX_POINTS = 4;

    const reloadImage = () => {
        setPoints([]);
        setImageUrl(`${imageUrl.split('?')[0]}?t=${Date.now()}`);
    }

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const img = new Image();
        img.src = imageUrl;
        img.crossOrigin = 'anonymous'; // Helps avoid CORS issues if processing pixels

        img.onload = () => {
            canvas.width = img.naturalWidth;
            canvas.height = img.naturalHeight;

            // Clear and draw background image
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

            if (points.length > 0) {
                ctx.strokeStyle = '#00ff00';
                ctx.lineWidth = 2;
                ctx.beginPath();
                const realPoints = points.map((p) => ({
                    x: p.x * img.width,
                    y: p.y * img.height,
                }));
                ctx.moveTo(realPoints[0].x, realPoints[0].y);

                realPoints.forEach((p) => {
                    ctx.lineTo(p.x, p.y);
                    // Draw point markers
                    ctx.fillStyle = '#ff0000';
                    ctx.fillRect(p.x - 4, p.y - 4, 8, 8);
                });

                if (realPoints.length === MAX_POINTS) {
                    ctx.closePath();
                }
                ctx.stroke();
            }
        };
    }, [points, imageUrl]);

    const handleCanvasClick = (e: MouseEvent<HTMLCanvasElement>): void => {
        if (points.length >= MAX_POINTS || !canvasRef.current) return;

        const canvas = canvasRef.current;
        const rect = canvas.getBoundingClientRect();

        // 1. Position on the screen (CSS Pixels)
        const cssX = e.clientX - rect.left;
        const cssY = e.clientY - rect.top;

        // 2. The ratio between the actual image pixels and the displayed size
        // We use the canvas internal width/height vs the bounding rect size
        const scaleX = canvas.width / rect.width;
        const scaleY = canvas.height / rect.height;

        // 3. Absolute Pixel Coordinates (What the backend needs to blur)
        const actualX = cssX * scaleX;
        const actualY = cssY * scaleY;

        // 4. Get the relative coordinates (0 to 1)
        const relativeX = actualX / canvas.width;
        const relativeY = actualY / canvas.height;

        // I recommend saving the Absolute Pixels for your immediate blurring task
        setPoints([...points, { x: relativeX, y: relativeY }]);
    };

    const submitToBackend = async (): Promise<void> => {
        if (points.length < MAX_POINTS) {
            alert('Please select 4 points first!');
            return;
        }

        try {
            const response = await addAnnotation(
                device,
                image.imagePath,
                points,
                user,
                "blur"
            );
            reloadImage();
        } catch (err) {
            console.error('Transmission error:', err);
        }
    };

    return (
        <div
            style={{
                fontFamily: 'sans-serif',
                textAlign: 'center',
                padding: '20px',
            }}
        >
            <h2>Area Selection Tool</h2>
            <canvas
                ref={canvasRef}
                width={windowWidth * 0.8}
                height={windowHeight * 0.6}
                onClick={handleCanvasClick}
                style={{
                    border: '1px solid #ccc',
                    cursor:
                        points.length < MAX_POINTS
                            ? 'crosshair'
                            : 'not-allowed',
                    boxShadow: '0 4px 6px rgba(0,0,0,0.1)',
                }}
            />
            <div style={{ marginTop: '15px' }}>
                <button
                    onClick={() => setPoints([])}
                    style={{ padding: '8px 16px', marginRight: '10px' }}
                >
                    Reset Points
                </button>
                <button
                    onClick={submitToBackend}
                    disabled={points.length < MAX_POINTS}
                    style={{ padding: '8px 16px', cursor: 'pointer' }}
                >
                    Apply Blur
                </button>
            </div>
            <p style={{ color: '#666' }}>
                Points selected:{' '}
                <strong>
                    {points.length} / {MAX_POINTS}
                </strong>
            </p>
        </div>
    );
};

export default Annotator;

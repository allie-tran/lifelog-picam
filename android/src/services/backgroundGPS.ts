import BackgroundService from 'react-native-background-actions';
import Geolocation from 'react-native-geolocation-service';
import { sendGPS, processGPS } from '../api/gps';

const SEND_INTERVAL_MS = 15_000;
const PROCESS_INTERVAL_MS = 60_000;

const sleep = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms));

const gpsTask = async (taskData: any) => {
  const { sensorDeviceId, deviceId } = taskData as { sensorDeviceId: string; deviceId: string };
  let lastProcessTime = 0;

  while (BackgroundService.isRunning()) {
    await new Promise<void>(resolve => {
      Geolocation.getCurrentPosition(
        async pos => {
          const { latitude, longitude, altitude } = pos.coords;
          const now = Date.now();
          try {
            await sendGPS(latitude, longitude, altitude ?? 0, sensorDeviceId, new Date().toISOString());
          } catch {}
          if (now - lastProcessTime > PROCESS_INTERVAL_MS) {
            lastProcessTime = now;
            processGPS(deviceId, new Date().toISOString().split('T')[0]).catch(() => {});
          }
          resolve();
        },
        () => resolve(),
        { enableHighAccuracy: true, timeout: 20_000, maximumAge: 30_000 },
      );
    });

    await sleep(SEND_INTERVAL_MS);
  }
};

const SERVICE_OPTIONS = {
  taskName: 'LifelogGPS',
  taskTitle: 'Lifelog GPS Tracking',
  taskDesc: 'Recording your location in the background',
  taskIcon: { name: 'ic_launcher', type: 'mipmap' },
  color: '#16A299',
};

export const startBackgroundGPS = (sensorDeviceId: string, deviceId: string) => {
  if (BackgroundService.isRunning()) { return Promise.resolve(); }
  return BackgroundService.start(gpsTask, {
    ...SERVICE_OPTIONS,
    parameters: { sensorDeviceId, deviceId },
  });
};

export const stopBackgroundGPS = () => BackgroundService.stop();

export const isBackgroundGPSRunning = () => BackgroundService.isRunning();

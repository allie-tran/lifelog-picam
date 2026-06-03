import { Box, FormControl, FormLabel, MenuItem, Select, Stack } from '@mui/material';
import axios from 'apis/defaultAxios';
import dayjs from 'dayjs';
import ReactECharts from 'echarts-for-react';
import React, { useState } from 'react';
import { useSearchParams } from 'react-router';
import { useAppSelector } from 'reducers/hooks';
import useSWR from 'swr';

interface MeasurementRecord {
    timeStamp: number;
    values: Record<string, number>;
}

const SENSORS = [
    'heartrate',
    'magnetometer',
    'gyroscope',
    'accelerometer',
    'ppg',
    'ppi',
];

export const SensorHistory: React.FC = () => {
    const [searchParams, _] = useSearchParams();
    const date = searchParams.get('date');
    const deviceId =
        useAppSelector((state) => state.auth.deviceId) ||
        searchParams.get('device') ||
        '';
    const today = dayjs().format('YYYY-MM-DD');

    // UI UX States
    const [selectedKey, setSelectedKey] = useState<string>('heartrate');

    // Execute Fetch Request to Backend API
    const {
        data: records,
        isLoading: loading,
        error,
    } = useSWR<Record<string, MeasurementRecord[]>>(
        {
            key: `browse/logs/${selectedKey}`,
            date,
            deviceId,
        },
        async () => {
            if (!date || !deviceId) return {};
            const res = await axios.get(`/browse/logs/${selectedKey}`, {
                params: {
                    date,
                    device_id: deviceId,
                },
            });
            if (selectedKey === '' && res.data.keys.length > 0)
                setSelectedKey(res.data.keys[0] || '');
            const logs = res.data.logs || {};
            return logs;
        },
        {
            revalidateOnFocus: false,
            revalidateOnReconnect: false,
            shouldRetryOnError: false,
            refreshInterval: date === today ? 10 * 60 * 1000 : 0,
        }
    );

    // Helper to convert 18-digit nanoseconds back to a readable time string for chart rendering
    const formatNsToTime = (s: number): string => {
        const localDate = new Date(s * 1000);
        return localDate.toLocaleTimeString([], {
            // day: '2-digit',
            // month: '2-digit',
            // year: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
        });
    };

    // --- ECHARTS LAYOUT BUILDER ---
    const subKeys = records?.[selectedKey]?.[0]?.values || {};

    const chartOption = {
        title: {
            text: selectedKey ? `${selectedKey}` : 'Heart Rate Log',
        },
        tooltip: {
            trigger: 'axis',
            formatter: (params: any) => {
                let res = `Time: ${params[0].name}<br/>`;
                params.forEach((item: any) => {
                    res += `${item.marker} ${item.seriesName}: <b>${item.value}</b><br/>`;
                });
                return res;
            },
        },
        legend: {
            data: Object.keys(subKeys).map(
                (subKey) => `${selectedKey} - ${subKey}`
            ),
            bottom: 0,
        },
        grid: { left: '4%', right: '4%', bottom: '15%', containLabel: true },
        toolbox: {
            feature: {
                dataZoom: { yAxisIndex: 'none' }, // Enables drag-and-zoom charting window tools
                restore: {},
                saveAsImage: {},
            },
        },
        xAxis: {
            type: 'category',
            data:
                records?.[selectedKey]?.map((record) =>
                    formatNsToTime(record.timeStamp)
                ) || [],
        },
        yAxis: {
            type: 'value',
            name: 'Value',
            min: 'dataMin',
            max: 'dataMax',
        },
        series: Object.keys(subKeys).map((subKey) => ({
            name: `${selectedKey} - ${subKey}`,
            type: 'line',
            data:
                records?.[selectedKey]?.map(
                    (record) => record.values[subKey]
                ) || [],
            smooth: true,
            lineStyle: {
                width: 2,
            },
        })),
    };

    if (!date) return null;
    if (!deviceId) return null;

    if (records && Object.keys(records).length === 0) {
        return null;
    }

    return (
        <Box sx={{ width: '100%' }}>
            <Stack
                direction="row"
                justifyContent="flex-end"
                spacing={2}
                sx={{  width: '100%' }}
            >
                <FormControl
                    size="small"
                >
                    <FormLabel sx={{ fontSize: 10 }}>Sensor Type</FormLabel>
                    <Select
                        size="small"
                        value={selectedKey}
                        onChange={(e) => setSelectedKey(e.target.value)}
                        sx={{ minWidth: 200 }}
                    >
                        {SENSORS.map((key) => (
                            <MenuItem key={key} value={key}>
                                {key}
                            </MenuItem>
                        ))}
                    </Select>
                </FormControl>
            </Stack>
            {/* Conditional Error Notification Layout Banner */}
            {error && (
                <div
                    style={{
                        backgroundColor: '#fee2e2',
                        color: '#991b1b',
                        padding: '12px',
                        borderRadius: '6px',
                        marginBottom: '20px',
                        fontWeight: 500,
                    }}
                >
                    {error}
                </div>
            )}

            {loading && (
                <div
                    style={{
                        height: '200px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: '#94a3b8',
                    }}
                >
                    Loading data...
                </div>
            )}

            {/* Interactive Chart Canvas Block Container */}
            {records && Object.keys(records).length > 0 ? (
                <ReactECharts
                    option={chartOption}
                    style={{ height: '200px', width: '100%' }}
                    notMerge={true}
                />
            ) : (
                <div
                    style={{
                        height: '200px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: '#94a3b8',
                        border: '2px dashed #e2e8f0',
                        borderRadius: '6px',
                    }}
                >
                    Enter a Device ID and load data
                </div>
            )}
        </Box>
    );
};

export default SensorHistory;

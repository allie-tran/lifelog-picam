// CategoryPieChart.tsx
import { Box, Typography, useTheme } from '@mui/material';
import { ArcElement, Chart as ChartJS, Legend, Tooltip } from 'chart.js';
import { CATEGORIES, THEME_COLORS } from 'constants/activityColors';
import React from 'react';
import { Doughnut } from 'react-chartjs-2';

ChartJS.register(ArcElement, Tooltip, Legend);

export type CategoryMinutes = {
    [category: string]: number;
};

interface CategoryPieChartProps {
    categoryMinutes: CategoryMinutes;
    totalMinutes: number;
    size?: number; // diameter in px
    strokeWidth?: number; // donut thickness
}

export const CategoryPieChart: React.FC<CategoryPieChartProps> = ({
    categoryMinutes,
    size = 180,
    strokeWidth = 24,
}) => {
    const theme = useTheme();

    const entries = Object.entries(categoryMinutes).filter(([_, m]) => m > 0);
    const totalMinutes = Object.values(categoryMinutes).reduce(
        (s, m) => s + m,
        0
    );

    if (entries.length === 0) {
        return (
            <Typography variant="body2" color="text.secondary">
                No theme data.
            </Typography>
        );
    }

    const labels = entries.map(([theme]) => theme);
    const values = entries.map(([, mins]) => mins);
    const backgroundColors = entries.map(
        ([theme]) => THEME_COLORS[theme as keyof typeof CATEGORIES] || theme
    );

    const data = {
        labels,
        datasets: [
            {
                data: values,
                backgroundColor: backgroundColors,
                borderWidth: 4,
                borderColor: theme.palette.background.paper,
            },
        ],
    };

    const options = {
        responsive: true,
        maintainAspectRatio: false as const,
        plugins: {
            legend: {
                position: 'right' as const,
                labels: {
                    usePointStyle: true,
                    color: theme.palette.text.primary,
                    font: {
                        size: 14,
                    },
                },
            },
            tooltip: {
                callbacks: {
                    label: (ctx: any) => {
                        const label = ctx.label ?? '';
                        const value = ctx.parsed ?? 0;
                        const total = values.reduce((s, v) => s + v, 0);
                        const pct =
                            total > 0
                                ? ((value / total) * 100).toFixed(1)
                                : '0.0';
                        return `${label}: ${value.toFixed?.(1) ?? value} min (${pct}%)`;
                    },
                },
            },
        },
    };

    return (
        <Box sx={{ width: '100%', height: 260 }}>
            <Doughnut data={data} options={options} />
        </Box>
    );
};

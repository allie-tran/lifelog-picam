import {
    Box,
    Chip,
    FormControl,
    InputLabel,
    MenuItem,
    Select,
    Stack,
    Switch,
    Typography,
} from '@mui/material';
import dayjs from 'dayjs';
import React, { useCallback, useEffect, useMemo } from 'react';
import Plot from 'react-plotly.js';
import { ColorScale } from 'plotly.js';
import {
    DayOfWeek,
    Month,
    Season,
    TimeOfDay,
    dayOfWeekOptions,
    timeOfDayOptions,
} from 'types/filters';
import weekOfYear from 'dayjs/plugin/weekOfYear';
import weekYear from 'dayjs/plugin/weekYear';
import dayOfYear from 'dayjs/plugin/dayOfYear';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';
import { ImageObject } from 'utils/types';

dayjs.extend(weekOfYear);
dayjs.extend(weekYear);
dayjs.extend(dayOfYear);
dayjs.extend(utc);
dayjs.extend(timezone);

const hourToTimeOfDayIndex = (hour: number): number => {
    if (hour >= 5 && hour < 11) return 0; // morning
    if (hour >= 11 && hour < 13) return 2; // midday
    if (hour >= 13 && hour < 17) return 1; // afternoon
    if (hour >= 17 && hour < 21) return 3; // evening
    return 4; // night
};

// Heatmap template (2D array) for time-based data
// TIME OF DAY: row = time of day, column = 365 days of the year
// DAY OF WEEK: row = day of week, column = 365 / 7 days of the year
const generateTimeHeatmapTemplate = (
    year: number,
    baseValue = 1
): number[][] => {
    const rows = timeOfDayOptions.length; // 5 time of day categories
    const columns =
        dayjs(`${year}-12-31`).diff(dayjs(`${year}-01-01`), 'day') + 1; // days in the year
    const heatmap: number[][] = [];
    for (let i = 0; i < rows; i++) {
        heatmap.push(new Array(columns).fill(baseValue));
    }
    return heatmap;
};

const fillTimeOfDayHeatmap = (heatmap: number[][], timeOfDay: TimeOfDay[]) => {
    if (timeOfDay.length === 0) return; // If no time of day filter is applied, skip
    for (let row = 0; row < heatmap.length; row++) {
        if (!timeOfDay.includes(timeOfDayOptions[row])) {
            // Increment count for all days (for simplicity, we assume activity is recorded for every day)
            for (let col = 0; col < heatmap[0].length; col++) {
                heatmap[row][col] = 0;
            }
        }
    }
};

const fillDayOfWeekHeatmap = (
    heatmap: number[][],
    dayOfWeek: DayOfWeek[],
    year: number
) => {
    if (dayOfWeek.length === 0) return; // If no day of week filter is applied, skip
    // Similar logic to fillTimeOfDayHeatmap, but based on day of week and corresponding columns
    for (let col = 0; col < heatmap[0].length; col++) {
        const date = dayjs(`${year}-01-01`).add(col, 'day');
        const dayName = date.format('dddd') as DayOfWeek;
        for (let row = 0; row < heatmap.length; row++) {
            heatmap[row][col] = dayOfWeek.includes(dayName)
                ? heatmap[row][col]
                : 0;
        }
    }
};

const getSeasonForMonth = (month: number): Season => {
    if (month >= 2 && month <= 4) return 'spring';
    if (month >= 5 && month <= 7) return 'summer';
    if (month >= 8 && month <= 10) return 'autumn';
    return 'winter';
};

const fillSeasonHeatmap = (
    heatmap: number[][],
    season: Season[],
    year: number
) => {
    if (season.length === 0) return; // If no season filter is applied, skip
    // Similar logic to fillTimeOfDayHeatmap, but based on season and corresponding columns
    for (let col = 0; col < heatmap[0].length; col++) {
        const date = dayjs(`${year}-01-01`).add(col, 'day');
        const month = date.month(); // 0-based month index
        const currentSeason = getSeasonForMonth(month);
        for (let row = 0; row < heatmap.length; row++) {
            heatmap[row][col] = season.includes(currentSeason)
                ? heatmap[row][col]
                : 0;
        }
    }
};

const fillMonthHeatmap = (
    heatmap: number[][],
    month: Month[],
    year: number
) => {
    // Similar logic to fillTimeOfDayHeatmap, but based on month and corresponding columns
    if (month.length === 0) return; // If no month filter is applied, skip
    for (let col = 0; col < heatmap[0].length; col++) {
        const date = dayjs(`${year}-01-01`).add(col, 'day');
        const monthName = date.format('MMMM') as Month;
        for (let row = 0; row < heatmap.length; row++) {
            heatmap[row][col] = month.includes(monthName)
                ? heatmap[row][col]
                : 0;
        }
    }
};

const getWeeklyView = (heatmap: number[][], year: number): number[][] => {
    const weeklyHeatmap: number[][] = [];
    const numRows = 7 * timeOfDayOptions.length; // 7 days of week * time of day categories
    const numCols =
        dayjs(`${year}-12-31`).week() - dayjs(`${year}-01-01`).week() + 1; // number of weeks in the year
    for (let row = 0; row < numRows; row++) {
        weeklyHeatmap.push(new Array(numCols).fill(0));
    }
    for (let col = 0; col < heatmap[0].length; col++) {
        const date = dayjs(`${year}-01-01`).add(col, 'day');
        const dayOfWeekIndex = (date.day() + 6) % 7; // Convert to 0=Monday, 6=Sunday
        let weekIndex = date.week() + (date.day() === 0 ? -2 : -1); // Adjust week index for Sundays
        const weekYear = date.weekYear();
        weekIndex += year - weekYear; // Adjust week index for year transitions
        for (let row = 0; row < heatmap.length; row++) {
            const weeklyRowIndex =
                dayOfWeekIndex * timeOfDayOptions.length + row;
            weeklyHeatmap[weeklyRowIndex][weekIndex] = heatmap[row][col];
        }
    }
    return weeklyHeatmap;
};

const getMonthlyView = (heatmap: number[][], year: number): number[][] => {
    const monthlyHeatmap: number[][] = [];
    const numRows = 12 * timeOfDayOptions.length; // 12 months * time of day categories
    const numCols = 12; // 12 months in the year
    for (let row = 0; row < numRows; row++) {
        monthlyHeatmap.push(new Array(numCols).fill(0));
    }
    for (let col = 0; col < heatmap[0].length; col++) {
        const date = dayjs(`${year}-01-01`).add(col, 'day');
        const monthIndex = date.month(); // 0-based month index
        for (let row = 0; row < heatmap.length; row++) {
            const monthlyRowIndex = monthIndex * timeOfDayOptions.length + row;
            monthlyHeatmap[monthlyRowIndex][monthIndex] = heatmap[row][col];
        }
    }
    return monthlyHeatmap;
};

// flip the value of the specified cells
const applyCustomCells = (
    heatmap: number[][],
    customCells: Set<{ row: number; col: number; value: number }>
) => {
    customCells.forEach(({ row, col, value }) => {
        heatmap[row][col] = value;
    });
};

const timeOfDayRanges: Record<string, string> = {
    morning: '05:00–11:00',
    afternoon: '13:00–17:00',
    midday: '11:00–13:00',
    evening: '17:00–21:00',
    night: '21:00–05:00',
};

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

const colorScale: ColorScale = [
    [0, '#02030310'],
    [1, '#16A29980'],
];

const nothingIsSelectedScale: ColorScale = [
    [0, 'transparent'],
    [1, '#02030320'],
];

const TimeHeatmap = ({
    timeOfDays: timeOfDay,
    dayOfWeeks: dayOfWeek,
    seasons: season,
    months: month,
    years: year,
    currentYear,
    customCells,
    setCustomCells,
    nothingIsSelected,
    noFiltersSelected,
    resultImages,
}: {
    timeOfDays: TimeOfDay[];
    dayOfWeeks: DayOfWeek[];
    seasons: Season[];
    months: Month[];
    years: number[];
    currentYear: number;
    customCells: Set<{ row: number; col: number; value: number }>;
    setCustomCells: React.Dispatch<
        React.SetStateAction<Set<{ row: number; col: number; value: number }>>
    >;
    nothingIsSelected: boolean;
    noFiltersSelected: boolean;
    resultImages: ImageObject[];
}) => {
    const [viewMode, setViewMode] = React.useState<
        'daily' | 'weekly' | 'monthly'
    >('daily');
    const [selectMode, setSelectMode] = React.useState<'fill' | 'clear'>(
        'fill'
    );
    const [timeOfDayHeatmap, setTimeOfDayHeatmap] =
        React.useState<number[][]>();

    useEffect(() => {
        let baseValue = 1;
        const excludeYear = year.length > 0 && !year.includes(currentYear);
        if (excludeYear || noFiltersSelected) {
            baseValue = 0;
        }
        const newHeatmap = generateTimeHeatmapTemplate(currentYear, baseValue);

        if (excludeYear) {
            setTimeOfDayHeatmap(newHeatmap);
            return; // If current year is excluded, skip further processing as heatmap will be all zeros
        }
        if (!noFiltersSelected) {
            // check year filter first, if year filter is applied and current year is not in the selected years, then we can skip filling the heatmap as it will be all zeros
            fillTimeOfDayHeatmap(newHeatmap, timeOfDay);
            fillDayOfWeekHeatmap(newHeatmap, dayOfWeek, currentYear);
            fillSeasonHeatmap(newHeatmap, season, currentYear);
            fillMonthHeatmap(newHeatmap, month, currentYear);
        }
        applyCustomCells(newHeatmap, customCells);
        setTimeOfDayHeatmap(newHeatmap);
    }, [
        currentYear,
        timeOfDay,
        dayOfWeek,
        season,
        month,
        customCells,
        nothingIsSelected,
        noFiltersSelected,
        year,
        currentYear,
    ]);

    const heatmapData = useMemo(() => {
        if (!timeOfDayHeatmap) return null;
        if (viewMode === 'daily') {
            const numCols = timeOfDayHeatmap[0].length;
            const hovertext = timeOfDayOptions.map((tod) =>
                Array.from({ length: numCols }, (_, col) => {
                    const date = dayjs(`${currentYear}-01-01`).add(col, 'day');
                    return `${date.format('ddd D MMM YYYY')}<br>${capitalize(tod)} (${timeOfDayRanges[tod]})`;
                })
            );
            return {
                z: timeOfDayHeatmap,
                x: Array.from({ length: numCols }, (_, i) => i + 1),
                y: timeOfDayOptions,
                ticktext: timeOfDayOptions,
                tickvals: timeOfDayOptions.map((_, i) => i),
                hovertext,
            };
        }
        if (viewMode === 'weekly') {
            const weeklyHeatmap = getWeeklyView(timeOfDayHeatmap, currentYear);
            const numRows = weeklyHeatmap.length;
            const numCols = weeklyHeatmap[0].length;
            const hovertext = Array.from({ length: numRows }, (_, row) => {
                const dayOfWeekIdx = Math.floor(row / timeOfDayOptions.length);
                const todIdx = row % timeOfDayOptions.length;
                const tod = timeOfDayOptions[todIdx];
                const dayName = dayOfWeekOptions[dayOfWeekIdx];
                return Array.from({ length: numCols }, (_, col) => {
                    const date = dayjs(`${currentYear}-01-01`).add(col * 7 + dayOfWeekIdx, 'day');
                    return `${dayName} ${date.format('D MMM YYYY')}<br>${capitalize(tod)} (${timeOfDayRanges[tod]})`;
                });
            });
            return {
                z: weeklyHeatmap,
                x: Array.from({ length: numCols }, (_, i) => `Week ${i + 1}`),
                y: dayOfWeekOptions.flatMap((day) =>
                    timeOfDayOptions.map((time) => `${day} - ${time}`)
                ),
                ticktext: dayOfWeekOptions.flatMap((day) => day.slice(0, 3)),
                tickvals: dayOfWeekOptions.map(
                    (_, i) => i * timeOfDayOptions.length + 2
                ),
                hovertext,
            };
        }
        if (viewMode === 'monthly') {
            const monthlyHeatmap = getMonthlyView(timeOfDayHeatmap, currentYear);
            const numRows = monthlyHeatmap.length;
            const hovertext = Array.from({ length: numRows }, (_, row) => {
                const monthIdx = Math.floor(row / timeOfDayOptions.length);
                const todIdx = row % timeOfDayOptions.length;
                const tod = timeOfDayOptions[todIdx];
                const monthName = dayjs().month(monthIdx).format('MMMM');
                return Array.from({ length: 12 }, () =>
                    `${monthName} ${currentYear}<br>${capitalize(tod)} (${timeOfDayRanges[tod]})`
                );
            });
            return {
                z: monthlyHeatmap,
                x: Array.from({ length: 12 }, (_, i) => dayjs().month(i).format('MMMM')),
                y: timeOfDayOptions,
                ticktext: timeOfDayOptions,
                tickvals: timeOfDayOptions.map((_, i) => i),
                hovertext,
            };
        }
    }, [timeOfDayHeatmap, viewMode, currentYear]);

    const handlePointClick = (point: any, value: number) => {
        const row = point[0];
        const col = point[1];

        let cellIndex = { row: row as number, col: col as number, value };
        if (viewMode === 'weekly') {
            cellIndex.col = col * 7 + Math.floor(row / timeOfDayOptions.length); // Convert back to day of year index
            cellIndex.row = row % timeOfDayOptions.length; // Get time of day index
        } else if (viewMode === 'monthly') {
            cellIndex.row = row % timeOfDayOptions.length; // Get time of day index
            cellIndex.col = col; // Month index corresponds to column
        }

        setCustomCells((prev) => {
            const newSet = new Set(prev);
            newSet.add(cellIndex);
            return newSet;
        });
    };

    const handleRangeSelect = useCallback(
        (event: any) => {
            if (!event.range) return;
            if (!timeOfDayHeatmap) return;
            const range = event.range as {
                x: [number, number];
                y: [number, number];
            };

            for (
                let row = Math.ceil(range.y[0]);
                row <= Math.floor(range.y[1]);
                row++
            ) {
                for (
                    let col = Math.ceil(range.x[0]);
                    col <= Math.floor(range.x[1]);
                    col++
                ) {
                    handlePointClick([row, col], selectMode === 'fill' ? 1 : 0);
                }
            }
        },
        [timeOfDayHeatmap, viewMode, selectMode]
    );

    useEffect(() => {
        // change selectmode if Alt key is pressed during selection
        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.altKey) {
                setSelectMode('clear');
            }
        };
        const handleKeyUp = (e: KeyboardEvent) => {
            if (e.key === 'Alt') {
                setSelectMode('fill');
            }
        };
        window.addEventListener('keydown', handleKeyDown);
        window.addEventListener('keyup', handleKeyUp);
    }, []);

    const resultDensityData = useMemo(() => {
        if (!resultImages.length || !heatmapData) return null;
        const daysInYear = dayjs(`${currentYear}-12-31`).diff(dayjs(`${currentYear}-01-01`), 'day') + 1;
        let numRows: number;
        let numCols: number;
        if (viewMode === 'daily') {
            numRows = timeOfDayOptions.length;
            numCols = daysInYear;
        } else if (viewMode === 'weekly') {
            numRows = 7 * timeOfDayOptions.length;
            numCols = dayjs(`${currentYear}-12-31`).week() - dayjs(`${currentYear}-01-01`).week() + 1;
        } else {
            numRows = 12 * timeOfDayOptions.length;
            numCols = 12;
        }
        const grid: number[][] = Array.from({ length: numRows }, () => new Array(numCols).fill(0));
        for (const img of resultImages) {
            const ts = dayjs.utc(img.timestamp).tz(img.timezone || 'UTC');
            if (ts.year() !== currentYear) continue;
            const hour = ts.hour();
            const todRow = hourToTimeOfDayIndex(hour);
            if (viewMode === 'daily') {
                const col = ts.dayOfYear() - 1;
                if (col >= 0 && col < numCols) grid[todRow][col]++;
            } else if (viewMode === 'weekly') {
                const dayOfWeekIdx = (ts.day() + 6) % 7;
                let weekIdx = ts.week() + (ts.day() === 0 ? -2 : -1);
                weekIdx += currentYear - ts.weekYear();
                const row = dayOfWeekIdx * timeOfDayOptions.length + todRow;
                if (weekIdx >= 0 && weekIdx < numCols && row >= 0 && row < numRows) grid[row][weekIdx]++;
            } else {
                const monthIdx = ts.month();
                const row = monthIdx * timeOfDayOptions.length + todRow;
                if (row >= 0 && row < numRows) grid[row][monthIdx]++;
            }
        }
        const maxVal = Math.max(...grid.flatMap(r => r));
        if (maxVal === 0) return null;
        return { z: grid.map(r => r.map(v => v === 0 ? 0 : v / maxVal)), x: heatmapData.x, y: heatmapData.y };
    }, [resultImages, currentYear, viewMode, heatmapData]);

    const plotData = useMemo(() => {
        if (!heatmapData) return null;
        const traces: any[] = [
            {
                x: heatmapData.x,
                y: heatmapData.y,
                z: heatmapData.z,
                type: 'heatmap',
                colorscale: nothingIsSelected ? nothingIsSelectedScale : colorScale,
                text: heatmapData.hovertext,
                hovertemplate: '%{text}<extra></extra>',
                hoverongaps: false,
                showscale: false,
                zmin: 0,
                zmax: 1,
            },
        ];
        if (resultDensityData) {
            traces.push({
                x: resultDensityData.x,
                y: resultDensityData.y,
                z: resultDensityData.z,
                type: 'heatmap',
                colorscale: [
                    [0, 'rgba(0,0,0,0)'],
                    [0.001, 'rgba(147,51,234,0.15)'],
                    [0.4, 'rgba(126,34,206,0.55)'],
                    [1, 'rgba(88,28,135,0.9)'],
                ] as ColorScale,
                hoverinfo: 'none',
                showscale: false,
                zmin: 0,
                zmax: 1,
            });
        }
        return traces;
    }, [heatmapData, nothingIsSelected, resultDensityData]);

    const layoutData = useMemo(
        () => ({
            height: 100,
            xaxis: {
                showgrid: true,
                ticklen: 0,
            },
            yaxis: {
                showgrid: false,
                autorange: 'reversed',
                ticklen: 0,
                tickvals: heatmapData?.tickvals,
                ticktext: heatmapData?.ticktext,
            },
            plot_bgcolor: 'transparent',
            paper_bgcolor: 'transparent',
            margin: { t: 0, r: 0, b: 0, l: 70 },
            showlegend: false,
            dragmode: 'select',
            newselection: {
                mode: 'immediate', // or 'gradual'
                line: {     // Outline thickness
                    dash: selectMode === 'fill' ? 'solid' : 'dot',
                    color: selectMode === 'fill' ? 'rgba(22, 162, 152, 0.8)' : 'rgba(255, 0, 0, 0.8)',
                }
            },
        }),
        [heatmapData, viewMode, selectMode, nothingIsSelected]
    );

    if (!heatmapData) return null;

    return (
        <Box sx={{ width: '100%' }}>
            <Stack direction="row" alignItems="center" mb={1}>
                <Typography color="primary" sx={{ pl: 1 }}>
                    Use the timeline to further specify the period that you want
                    to search
                </Typography>
                <FormControl
                    sx={{ width: '200px', marginLeft: 'auto' }}
                    size="small"
                >
                    <InputLabel id="view-mode-label">View Mode</InputLabel>
                    <Select
                        labelId="view-mode-label"
                        value={viewMode}
                        label="View Mode"
                        onChange={(e) => {
                            setViewMode(e.target.value as 'daily' | 'weekly');
                        }}
                    >
                        <MenuItem value="daily">Time of Day</MenuItem>
                        <MenuItem value="weekly">Day of Week</MenuItem>
                        <MenuItem value="monthly">Month</MenuItem>
                    </Select>
                </FormControl>
            </Stack>
            <Stack
                direction="row"
                alignItems="center"
                mb={1}
                justifyContent="flex-end"
                sx={{ width: '100%' }}
            >
                <Typography sx={{ mr: 1, fontSize: '0.8rem' }}>
                    {selectMode === 'fill' ? 'Hold Alt key to clear cells' : ''}
                </Typography>
                <Chip size="small" label="Clearing" color={selectMode === 'clear' ? 'primary' : 'default'} />
                <Switch 
                    checked={selectMode === 'fill'}
                    onChange={(e) => {
                        setSelectMode(e.target.checked ? 'fill' : 'clear');
                    }}
                    size="small"
                    color={selectMode === 'fill' ? 'secondary' : 'primary'}
                />
                <Chip size="small" label="Adding" color={selectMode === 'fill' ? 'secondary' : 'default'} />
            </Stack>
            <Plot
                onSelected={handleRangeSelect}
                data={plotData as any}
                layout={layoutData as any}
                style={{ width: '100%', height: '100%' }}
                config={{
                    // staticPlot: true,
                    displayModeBar: false,
                }}
                
            />
        </Box>
    );
};

export default TimeHeatmap;

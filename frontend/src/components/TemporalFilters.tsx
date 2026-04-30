import {
    Box,
    Button,
    Checkbox,
    Chip,
    Grid,
    Stack,
    Tab,
    Tabs,
    Typography,
    styled,
} from '@mui/material';
import { useState } from 'react';
import {
    DayOfWeek,
    Month,
    Season,
    TimeOfDay,
    dayOfWeekOptions,
    monthOptions,
    seasonOptions,
    timeOfDayOptions,
} from 'types/filters';
import TimeHeatmap from './TimeHeatmap';
import useSWR from 'swr';
import { getAvailableValues } from '@apis/searchFilters';
import { useAppDispatch, useAppSelector } from 'reducers/hooks';
import { setSearchQuery } from 'reducers/search';

const TemporalFiltersHook = () => {
    const dispatch = useAppDispatch();
    const deviceId = useAppSelector((state) => state.auth.deviceId);
    const [tabIndex, setTabIndex] = useState(0);
    const [currentYear, setCurrentYear] = useState<number>(
        new Date().getFullYear()
    );
    const [customCells, setCustomCells] = useState<
        Set<{ row: number; col: number; value: number }>
    >(new Set());
    const { timeOfDays, dayOfWeeks, seasons, months, years } = useAppSelector(
        (state) => state.search.query
    );

    const { data: availableYears } = useSWR([deviceId, 'year'], async () => {
        const years = await getAvailableValues(deviceId, 'year');
        setCurrentYear(
            years.length > 0 ? parseInt(years[0]) : new Date().getFullYear()
        );
        return years.map((y) => parseInt(y));
    });

    const nothingIsSelected =
        timeOfDays.length === 0 &&
        dayOfWeeks.length === 0 &&
        seasons.length === 0 &&
        months.length === 0 &&
        years.length === 0 &&
        customCells.size === 0;

    const noFiltersSelected =
        timeOfDays.length === 0 &&
        dayOfWeeks.length === 0 &&
        seasons.length === 0 &&
        months.length === 0 &&
        years.length === 0;

    const renderFilterOptions = () => (
        <Box>
            <Tabs
                value={tabIndex}
                onChange={(_, newValue) => setTabIndex(newValue)}
                sx={{
                    borderBottom: 1,
                    borderColor: 'divider',
                    minHeight: '32px',
                }}
                variant="scrollable"
                scrollButtons="auto"
            >
                <StyledTab label="Time of Day" />
                <StyledTab label="Day of Week" />
                <StyledTab label="Season" />
                <StyledTab label="Month" />
                <StyledTab label="Year" />
            </Tabs>

            {/* Render filter options based on selected tab */}
            {tabIndex === 0 && (
                <ListOfCheckBoxes
                    options={timeOfDayOptions}
                    selectedOptions={timeOfDays}
                    onChange={(selected) =>
                        dispatch(
                            setSearchQuery({
                                timeOfDays: selected as TimeOfDay[],
                            })
                        )
                    }
                />
            )}
            {tabIndex === 1 && (
                <ListOfCheckBoxes
                    options={dayOfWeekOptions}
                    selectedOptions={dayOfWeeks}
                    onChange={(selected) =>
                        dispatch(
                            setSearchQuery({
                                dayOfWeeks: selected as DayOfWeek[],
                            })
                        )
                    }
                />
            )}
            {tabIndex === 2 && (
                <ListOfCheckBoxes
                    options={seasonOptions}
                    selectedOptions={seasons}
                    onChange={(selected) =>
                        dispatch(
                            setSearchQuery({ seasons: selected as Season[] })
                        )
                    }
                />
            )}
            {tabIndex === 3 && (
                <ListOfCheckBoxes
                    options={monthOptions}
                    selectedOptions={months}
                    onChange={(selected) =>
                        dispatch(
                            setSearchQuery({ months: selected as Month[] })
                        )
                    }
                />
            )}
            {tabIndex === 4 && (
                <ListOfCheckBoxes
                    options={availableYears ? availableYears.map(String) : []}
                    selectedOptions={years.map(String)}
                    onChange={(selected) =>
                        dispatch(setSearchQuery({ years: selected.map(Number) }))
                    }
                />
            )}
        </Box>
    );

    const renderHeatmap = () => {
        return (
            <Stack alignItems="center" mt={4}>
                <TimeHeatmap
                    timeOfDays={timeOfDays}
                    dayOfWeeks={dayOfWeeks}
                    seasons={seasons}
                    months={months}
                    years={years}
                    currentYear={currentYear}
                    customCells={customCells}
                    setCustomCells={setCustomCells}
                    nothingIsSelected={nothingIsSelected}
                    noFiltersSelected={noFiltersSelected}
                />

                <Stack direction="row" alignItems="center" spacing={1} mt={2}>
                    <Typography variant="body2">Year:</Typography>
                    {availableYears?.map((yr) => (
                        <Chip
                            key={yr}
                            label={yr}
                            variant={currentYear === yr ? 'filled' : 'outlined'}
                            size="small"
                            onClick={() => setCurrentYear(yr)}
                        />
                    ))}
                </Stack>
            </Stack>
        );
    };

    const renderClearButton = () => {
        return (
            <Button
                disabled={nothingIsSelected}
                variant="outlined"
                color="primary"
                sx={{ mt: 2 }}
                onClick={() => {
                    dispatch(
                        setSearchQuery({
                            timeOfDays: [],
                            dayOfWeeks: [],
                            seasons: [],
                            months: [],
                            years: [],
                        })
                    );
                    setCustomCells(new Set());
                }}
            >
                Clear Filters
            </Button>
        );
    };

    return {
        renderFilterOptions,
        renderHeatmap,
        renderClearButton,
        nothingIsSelected,
    };
};

const ListOfCheckBoxes = ({
    options,
    selectedOptions,
    onChange,
}: {
    options: string[];
    selectedOptions: string[];
    onChange: (selected: string[]) => void;
}) => {
    return (
        <Grid container spacing={1} mt={1}>
            <CheckboxWithText
                label="All"
                checked={selectedOptions.length === options.length}
                onChange={(checked) => {
                    if (checked) {
                        onChange(options);
                    } else {
                        onChange([]);
                    }
                }}
            />
            {options.map((option) => (
                <CheckboxWithText
                    key={option}
                    label={option}
                    checked={selectedOptions.includes(option)}
                    onChange={(checked) => {
                        if (checked) {
                            onChange([...selectedOptions, option]);
                        } else {
                            onChange(
                                selectedOptions.filter((o) => o !== option)
                            );
                        }
                    }}
                />
            ))}
            <CheckboxWithText
                label="None"
                disabled={selectedOptions.length === 0}
                checked={false}
                onChange={(checked) => {
                    if (checked) {
                        onChange([]);
                    }
                }}
            />
        </Grid>
    );
};

const StyledTab = styled(Tab)({
    borderRadius: '8px px 0 0',
    marginRight: '4px',
    fontSize: '12px',
    minHeight: '32px',
    padding: '4px 12px',
    '&.Mui-selected': {
        backgroundColor: 'primary.main',
        color: 'primary.contrastText',
    },
});

const CheckboxWithText = ({
    label,
    checked,
    onChange,
    disabled = false,
}: {
    label: string;
    checked: boolean;
    onChange: (checked: boolean) => void;
    disabled?: boolean;
}) => {
    return (
        <Grid size={4} sx={{ overflow: 'hidden', whiteSpace: 'nowrap' }}>
            <Checkbox
                size="small"
                disabled={disabled}
                checked={checked}
                onChange={(e) => onChange(e.target.checked)}
                sx={{ padding: '4px' }}
            />
            <Typography
                variant="caption"
                sx={{ display: 'inline-block', ml: -0.5 }}
            >
                {label.slice(0, 1).toUpperCase() + label.slice(1)}
            </Typography>
        </Grid>
    );
};

export { TemporalFiltersHook };

import {
    Badge,
    Button,
    ButtonProps,
    Stack,
    styled,
    TextField
} from '@mui/material';
import { PickersDay, PickersDayProps } from '@mui/x-date-pickers';
import { DatePicker } from '@mui/x-date-pickers/DatePicker';
import dayjs from 'dayjs';
import React, { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { useAppSelector } from 'reducers/hooks';
import '../App.css';

const AvailableDay = (props: PickersDayProps & { allDates: string[] }) => {
    const { allDates = [], day, outsideCurrentMonth, ...other } = props;
    if (!allDates.includes(day.format('YYYY-MM-DD'))) {
        return (
            <PickersDay
                {...other}
                day={day}
                outsideCurrentMonth={outsideCurrentMonth}
            />
        );
    }

    return (
        <Badge key={day.toString()} variant="dot" color="primary">
            <PickersDay
                {...other}
                day={day}
                outsideCurrentMonth={outsideCurrentMonth}
            />
        </Badge>
    );
};

const CustomButton = styled('button')({
    height: 36,
    width: 72,
    backgroundColor: 'transparent',
    color: 'inherit',
    border: 'none',
    cursor: 'pointer',
    fontSize: '0.875rem',
});

const AvailableYear = (props: ButtonProps & { allYears: string[] }) => {
    const { allYears = [], children, ...other } = props;
    const year = dayjs(children as string).format('YYYY');

    if (!allYears.includes(year)) {
        return <CustomButton {...other}>{children}</CustomButton>;
    }

    return (
        <Badge key={year} variant="dot" color="primary">
            <CustomButton {...other}>{children}</CustomButton>
        </Badge>
    );
};

const AvailableMonth = (
    props: ButtonProps & { allMonths: string[]; year: string }
) => {
    const { allMonths = [], children, year, ...other } = props;
    console.log('AvailableMonth props:', props);
    const month = `${year}-${children}`;

    if (!allMonths.includes(month)) {
        return <CustomButton {...other}>{children}</CustomButton>;
    }
    return (
        <Badge key={month} variant="dot" color="primary">
            {' '}
            <CustomButton {...other}>{children}</CustomButton>
        </Badge>
    );
};

const CustomDatePicker = ({
    date,
    setPage,
    setHour,
    allDates,
}: {
    date: string | null;
    setPage: (page: number) => void;
    setHour: (hour: number | null) => void;
    allDates: string[] | undefined;
}) => {
    const navigate = useNavigate();
    const today = dayjs().format('YYYY-MM-DD');
    const deviceId = useAppSelector((state) => state.auth.deviceId) || '';
    const [searchParams, _] = useSearchParams();
    const [usePicker, setUsePicker] = React.useState(true);
    const [textDate, setTextDate] = React.useState(date || '');

    const allMonths = React.useMemo(() => {
        if (!allDates) return [];
        const uniqueMonths = new Set(
            allDates.map((date) => dayjs(date).format('YYYY-MMM'))
        );
        return Array.from(uniqueMonths);
    }, [allDates]);

    const allYears = React.useMemo(() => {
        if (!allDates) return [];
        const uniqueYears = new Set(
            allDates.map((date) => dayjs(date).format('YYYY'))
        );
        return Array.from(uniqueYears);
    }, [allDates]);

    const goToNextDate = () => {
        if (!date) return;
        const nextDate = dayjs(date).add(1, 'day').format('YYYY-MM-DD');
        setPage(1);
        setHour(null);
        searchParams.set('date', nextDate);
        navigate({ search: searchParams.toString() });
    };

    const goToPreviousDate = () => {
        if (!date) return;
        const prevDate = dayjs(date).subtract(1, 'day').format('YYYY-MM-DD');
        setPage(1);
        setHour(null);
        searchParams.set('date', prevDate);
        navigate({ search: searchParams.toString() });
    };

    useEffect(() => {
        if (!date) {
            searchParams.set('date', today);
            navigate({ search: searchParams.toString() });
        }
    }, [date, navigate, today]);

    useEffect(() => {
        setTextDate(date ? dayjs(date).format('DD/MM/YYYY') : '');
    }, [date]);



    return (
        <>
            <Stack>
                <Button
                    size="small"
                    onClick={goToPreviousDate}
                    sx={{ mt: 1 }}
                    variant="outlined"
                >
                    Previous
                </Button>
                <Button
                    size="small"
                    onClick={goToNextDate}
                    sx={{ mt: 1 }}
                    variant="outlined"
                >
                    Next
                </Button>
            </Stack>
            {usePicker ? (
                <DatePicker
                    disableFuture
                    formatDensity='spacious'
                    label="Select Date"
                    value={date ? dayjs(date) : null}
                    views={['year', 'month', 'day']}
                    sx={{ width: '250px', transform: 'translateY(4px)' }}
                    onChange={(newValue) => {
                        setPage(1);
                        setHour(null);
                        searchParams.set('date', newValue ? newValue.format('YYYY-MM-DD') : '');
                        navigate({ search: searchParams.toString() });
                    }}
                    slots={{
                        day: (props) => (
                            <AvailableDay
                                {...props}
                                allDates={allDates || []}
                            />
                        ),
                        monthButton: (props) => (
                            <AvailableMonth
                                allMonths={allMonths}
                                {...props}
                                year={date ? dayjs(date).format('YYYY') : ''}
                            />
                        ),
                        yearButton: (props) => (
                            <AvailableYear allYears={allYears} {...props} />
                        ),
                    }}
                    referenceDate={date ? dayjs(date) : dayjs() }
                />
            ) : (
                <TextField
                    label="Select Date"
                    value={textDate}
                    onChange={(e) => setTextDate(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            setPage(1);
                            setHour(null);
                            searchParams.set('date', dayjs(textDate, 'DD/MM/YYYY').format('YYYY-MM-DD'));
                            navigate({ search: searchParams.toString() });
                        }
                    }}
                    sx={{ width: '250px', transform: 'translateY(4px)' }}
                />
            )}
            <Button
                onClick={() => setUsePicker(!usePicker)}
                sx={{ marginLeft: 2 }}
                variant="contained"
            >
                {usePicker ? 'Use Text' : 'Use Day Picker'}
            </Button>
        </>
    );
};

export default CustomDatePicker;

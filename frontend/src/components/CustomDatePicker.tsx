import {
    Badge,
    Button,
    ButtonProps,
    Divider,
    IconButton,
    InputAdornment,
    Popover,
    Stack,
    TextField,
    styled,
} from '@mui/material';
import {
    ArrowLeftRounded,
    ArrowRightRounded,
    CalendarMonthRounded,
    FastForwardRounded,
    FastRewindRounded,
    TodayRounded,
} from '@mui/icons-material';
import { DateCalendar } from '@mui/x-date-pickers/DateCalendar';
import { PickersDay, PickersDayProps } from '@mui/x-date-pickers';
import dayjs, { Dayjs } from 'dayjs';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
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
    const month = `${year}-${children}`;
    if (!allMonths.includes(month)) {
        return <CustomButton {...other}>{children}</CustomButton>;
    }
    return (
        <Badge key={month} variant="dot" color="primary">
            <CustomButton {...other}>{children}</CustomButton>
        </Badge>
    );
};

const DATE_FORMATS = [
    'D MMM YYYY',
    'D MMMM YYYY',
    'YYYY-MM-DD',
    'DD/MM/YYYY',
    'D/M/YYYY',
    'M/D/YYYY',
];

const parseDate = (text: string): Dayjs | null => {
    for (const fmt of DATE_FORMATS) {
        const d = dayjs(text.trim(), fmt, true);
        if (d.isValid()) return d;
    }
    const d = dayjs(text.trim());
    return d.isValid() ? d : null;
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
    const [searchParams] = useSearchParams();
    const [textDate, setTextDate] = useState(
        date ? dayjs(date).format('D MMM YYYY') : ''
    );
    const [textError, setTextError] = useState(false);
    const [calendarAnchor, setCalendarAnchor] = useState<HTMLElement | null>(
        null
    );

    const allDatesSet = useMemo(() => new Set(allDates ?? []), [allDates]);

    const allMonths = useMemo(() => {
        if (!allDates) return [];
        return Array.from(
            new Set(allDates.map((d) => dayjs(d).format('YYYY-MMM')))
        );
    }, [allDates]);

    const allYears = useMemo(() => {
        if (!allDates) return [];
        return Array.from(
            new Set(allDates.map((d) => dayjs(d).format('YYYY')))
        );
    }, [allDates]);

    const referenceDate = useMemo(() => {
        if (allDates && allDates.length > 0) {
            if (date && allDatesSet.has(date)) return dayjs(date);
            return dayjs(allDates[allDates.length - 1]);
        }
        return date ? dayjs(date) : dayjs();
    }, [allDates, date, allDatesSet]);

    useEffect(() => {
        if (!date) {
            const newParams = new URLSearchParams(searchParams.toString());
            if (allDates && allDates.length > 0) {
                newParams.set('date', allDates[allDates.length - 1]);
            } else {
                newParams.set('date', today);
            }
            navigate({ search: newParams.toString() });
        }
    }, [date, navigate, today, searchParams]);

    useEffect(() => {
        setTextDate(date ? dayjs(date).format('D MMM YYYY') : '');
        setTextError(false);
    }, [date]);

    const navigateToDate = (parsed: Dayjs) => {
        const newParams = new URLSearchParams(searchParams.toString());
        setPage(1);
        setHour(null);
        newParams.set('date', parsed.format('YYYY-MM-DD'));
        navigate({ search: newParams.toString() });
    };

    const handleTextCommit = () => {
        if (!textDate.trim()) return;
        const parsed = parseDate(textDate);
        if (parsed) {
            setTextError(false);
            navigateToDate(parsed);
        } else {
            setTextError(true);
        }
    };

    const goToNextDate = () => {
        if (!date) return;
        navigateToDate(dayjs(date).add(1, 'day'));
    };

    const goToPreviousDate = () => {
        if (!date) return;
        navigateToDate(dayjs(date).subtract(1, 'day'));
    };

    return (
        <Stack direction="row" alignItems="center" spacing={1}>
            <IconButton
                size="small"
                onClick={goToPreviousDate}
                sx={{ border: '1px solid', borderColor: 'divider' }}
            >
                <ArrowLeftRounded />
            </IconButton>
            <TextField
                label="Date"
                value={textDate}
                onChange={(e) => {
                    setTextDate(e.target.value);
                    setTextError(false);
                }}
                onKeyDown={(e) => e.key === 'Enter' && handleTextCommit()}
                onBlur={handleTextCommit}
                error={textError}
                helperText={textError ? 'Try: 15 Jun 2024' : ' '}
                size="small"
                sx={{ width: 200, transform: 'translateY(12px)' }}
                slotProps={{
                    input: {
                        endAdornment: (
                            <InputAdornment position="end">
                                <IconButton
                                    size="small"
                                    edge="end"
                                    onClick={(e) =>
                                        setCalendarAnchor(e.currentTarget)
                                    }
                                >
                                    <CalendarMonthRounded fontSize="small" />
                                </IconButton>
                            </InputAdornment>
                        ),
                    },
                }}
            />
            <Popover
                open={!!calendarAnchor}
                anchorEl={calendarAnchor}
                onClose={() => setCalendarAnchor(null)}
                anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
                transformOrigin={{ vertical: 'top', horizontal: 'center' }}
            >
                <DateCalendar
                    disableFuture
                    value={date ? dayjs(date) : null}
                    shouldDisableDate={(day) =>
                        allDatesSet.size > 0 &&
                        !allDatesSet.has(day.format('YYYY-MM-DD'))
                    }
                    onChange={(newValue: Dayjs | null) => {
                        if (newValue) {
                            setCalendarAnchor(null);
                            navigateToDate(newValue);
                        }
                    }}
                    referenceDate={referenceDate}
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
                />
                <Divider />
                {allDates ? (
                    <Stack
                        alignItems="center"
                        justifyContent="center"
                        py={1}
                        direction="row"
                        spacing={2}
                        divider={<Divider orientation="vertical" flexItem />}
                    >
                        <Button
                            size="small"
                            onClick={() => {
                                setCalendarAnchor(null);
                                navigateToDate(dayjs(allDates[0]));
                            }}
                        >
                            <FastRewindRounded sx={{ mr: 0.5 }} />
                            First Available
                        </Button>
                        <Button
                            size="small"
                            onClick={() => {
                                setCalendarAnchor(null);
                                navigateToDate(
                                    dayjs(allDates[allDates.length - 1])
                                );
                            }}
                        >
                            Last Available
                            <FastForwardRounded sx={{ ml: 0.5 }} />
                        </Button>
                    </Stack>
                ) : (
                    <Button
                        size="small"
                        onClick={() => {
                            setCalendarAnchor(null);
                            navigateToDate(dayjs());
                        }}
                    >
                        <TodayRounded sx={{ mr: 0.5 }} />
                        Today
                    </Button>
                )}
            </Popover>
            <IconButton
                size="small"
                onClick={goToNextDate}
                sx={{ border: '1px solid', borderColor: 'divider' }}
            >
                <ArrowRightRounded />
            </IconButton>
        </Stack>
    );
};

export default CustomDatePicker;

import { Badge, Button, ButtonProps, styled, Theme } from '@mui/material';
import { PickersDay, PickersDayProps } from '@mui/x-date-pickers';
import { DatePicker } from '@mui/x-date-pickers/DatePicker';
import dayjs from 'dayjs';
import React from 'react';
import { useNavigate } from 'react-router';
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

    return (
        <DatePicker
            label="Select Date"
            value={date ? dayjs(date) : null}
            views={['year', 'month', 'day']}
            sx={{ width: '250px', transform: 'translateY(4px)' }}
            onChange={(newValue) => {
                setPage(1);
                setHour(null);
                navigate(`/?date=${newValue?.format('YYYY-MM-DD') || ''}`);
            }}
            slots={{
                day: (props) => (
                    <AvailableDay {...props} allDates={allDates || []} />
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
    );
};

export default CustomDatePicker;

from datetime import datetime, timezone

import pytest

from services.date_utils import parse_date


def test_parse_basename_no_timezone():
    assert parse_date("20240115_143005") == datetime(2024, 1, 15, 14, 30, 5)


def test_parse_basename_with_offset():
    dt = parse_date("20240115_143005+0000")
    assert dt == datetime(2024, 1, 15, 14, 30, 5, tzinfo=timezone.utc)


def test_parse_basename_with_utc_suffix():
    # The "%Y%m%d_%H%M%S_%Z" format matches a trailing named zone.
    assert parse_date("20240115_143005_UTC") == datetime(2024, 1, 15, 14, 30, 5)


def test_unparseable_raises_valueerror():
    with pytest.raises(ValueError):
        parse_date("not-a-timestamp")

from datetime import datetime
def parse_date(basename: str) -> datetime:

    formats = [
        "%Y%m%d_%H%M%S%z",
        "%Y%m%d_%H%M%S_%Z",
        "%Y%m%d_%H%M%S",
    ]

    for fmt in formats:
        try:
            timestamp = datetime.strptime(basename, fmt)
            return timestamp
        except ValueError:
            continue

    raise ValueError(f"Unable to parse date from basename: {basename}")

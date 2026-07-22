from datetime import datetime
def parse_date(basename: str) -> datetime:

    formats = [
        "%Y%m%d_%H%M%S%z",
        "%Y%m%d_%H%M%S_%Z",
        "%Y%m%d_%H%M%S",
        "%Y%m%d_%H%M%S_UTC",
    ]

    for fmt in formats:
        try:
            timestamp = datetime.strptime(basename, fmt)
            return timestamp
        except ValueError:
            print(f"Failed to parse {basename} with format {fmt}")
            continue

    raise ValueError(f"Unable to parse date from basename: {basename}")

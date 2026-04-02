from dateutil import parser

def parse_date(date_str):
    if "BST" in date_str:
        date_str = date_str.replace("BST", "+0100")
    elif "GMT" in date_str:
        date_str = date_str.replace("GMT", "+0000")
    return parser.parse(date_str)


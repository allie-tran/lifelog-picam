from collections import defaultdict

DIR = "/mnt/ssd0/LifelogPicam"  # Directory to store images
THUMBNAIL_DIR = "/mnt/ssd0/Images/LifelogPicam"  # Directory to store thumbnails
LOCAL_PORT = 8082
SEARCH_MODEL = "conclip"
SEGMENT_THRESHOLD = 0.9  # Threshold for segmentation, lower means more segments

CATEGORIES_WITH_GROUPS = {
    "Work – Research & Writing": {
        "activities": [
            "Writing",
            "Coding",
            "Email & Admin",
            "Taking Notes",
        ],
        "color": "#1f618d",
    },
    "Meetings & Collaboration": {
        "activities": [
            "Meeting",
            "Zoom Call",
            "Conference / Workshop",
        ],
        "color": "#117864",
    },
    "Teaching & Outreach": {
        "activities": [
            "Lecturing",
            "Lab / Tutorial",
            "Course Prep",
            "Public Talk",
        ],
        "color": "#f39c12",
    },
    "Travel": {
        "activities": [
            "Commuting",
            "Travelling (Train)",
            "Travelling (Plane)",
            "Traveling (Bus)",
            "Traveling (Car)",
            "Walking on Campus",
            "Packing / Unpacking",
        ],
        "color": "#7f8c8d",
    },
    "Food & Drink": {
        "activities": [
            "Eating",
            "Drinking",
            "Making Coffee",
            "Making Tea",
            "Cooking at Home",
            "Eating Out",
        ],
        "color": "#e67e22",
    },
    "Leisure & Wellbeing": {
        "activities": [
            "Reading",
            "Watching TV",
            "Listening to Music",
            "Exercise / Gym",
            "Photography / Journaling",
            "Relaxing / Doing Nothing",
        ],
        "color": "#9b59b6",
    },
    "Social & Personal": {
        "activities": [
            "Talking with People",
            "Video Call",
            "Family Time",
            "Shopping / Errands",
            "House Cleaning",
            "Tidying Up",
            "Laundry / Chores",
            "Organizing Workspace",
            "Personal Care",
        ],
        "color": "#c0392b",
    },
    "Sleep / Downtime": {
        "activities": [
            "Sleeping",
            "Resting",
            "Napping",
        ],
        "color": "#2c3e50",
    },
    "Miscellaneous": {
        "activities": [
            "Transit / Waiting",
            "Unclear Activity",
            "No Activity",
        ],
        "color": "#95a5a6",
    },
}

DELETED_ACTIVITIES = [
    "Talking with Friends",
    "Video Call with Partner",
    "Paper Writing",
    "Grant Writing",
    "Coding / Experimenting",
    "Data Analysis",
    "Reading Papers",
    "Supervising Students",
    "Giving Feedback",
    "Conference Travel",
    "Team Meeting",
    "One-to-One Meeting",
    "Conference Call",
    "Seminar / Talk",
    "Presentation Prep",
    "Grading / Assessment",
    "Outreach / Public Talk",
    "Walking for Leisure",
    "Organizing Workspace",
    "Watching TV / Series",
]


CATEGORIES = defaultdict(lambda: "Unclear Activity")
for group, details in CATEGORIES_WITH_GROUPS.items():
    for activity in details["activities"]:
        if activity not in DELETED_ACTIVITIES:
            CATEGORIES[activity] = details["color"]

GROUPED_CATEGORIES = defaultdict(lambda: "Miscellaneous")
for group, details in CATEGORIES_WITH_GROUPS.items():
    for activity in details["activities"]:
        GROUPED_CATEGORIES[activity] = group

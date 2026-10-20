"""Fixed domain tables shared by the API and the loader scripts (spec §2, spec-api §2)."""

HAZARDS = {
    "POTHOLE": {"label": "Pothole", "label_ms": "Lubang jalan", "color": "#6B7280", "icon": "pothole"},
    "FALLEN_TREE": {"label": "Fallen tree", "label_ms": "Pokok tumbang", "color": "#16A34A", "icon": "tree"},
    "SINKHOLE": {"label": "Sinkhole", "label_ms": "Lubang benam", "color": "#8B4513", "icon": "sinkhole"},
}

# Peninsular states: code -> (name, federal maintenance zone)
STATES = {
    "R": ("Perlis", "NORTH"),
    "K": ("Kedah", "NORTH"),
    "P": ("Pulau Pinang", "NORTH"),
    "A": ("Perak", "NORTH"),
    "B": ("Selangor", "CENTRAL_EAST"),
    "C": ("Pahang", "CENTRAL_EAST"),
    "T": ("Terengganu", "CENTRAL_EAST"),
    "D": ("Kelantan", "CENTRAL_EAST"),
    "J": ("Johor", "SOUTH"),
    "M": ("Melaka", "SOUTH"),
    "N": ("Negeri Sembilan", "SOUTH"),
    # Federal maintainer for the Federal Territories is an open question (plan §10 Q2).
    "KUL": ("WP Kuala Lumpur", "FT"),
    "PJY": ("WP Putrajaya", "FT"),
}

RISK_LEVELS = {"LOW": (0.0, 0.2), "MEDIUM": (0.2, 0.4), "HIGH": (0.4, 0.7), "VERY_HIGH": (0.7, 1.0)}


def risk_level(probability: float) -> str:
    for level, (low, high) in RISK_LEVELS.items():
        if low <= probability < high:
            return level
    return "VERY_HIGH"

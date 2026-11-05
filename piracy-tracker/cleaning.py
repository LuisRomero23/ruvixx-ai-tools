NULL_LIKE_VALUES = {"", "N/A", "NA", "NULL", "NONE", "-", "?"}

COUNTRY_ALIASES = {
    "usa": "United States",
    "us": "United States",
    "u.s.": "United States",
    "u.s.a.": "United States",
    "united states of america": "United States",
    "united states": "United States",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "great britain": "United Kingdom",
    "united kingdom": "United Kingdom",
}


def normalize_device_id(value):
    if value is None:
        return None
    normalized = value.strip().upper()
    if normalized in NULL_LIKE_VALUES:
        return None
    return normalized


def normalize_country(value):
    normalized = " ".join((value or "").split()).replace(".", "").casefold()
    if not normalized:
        return "Unknown"
    alias = COUNTRY_ALIASES.get(normalized)
    if alias is not None:
        return alias
    return normalized.title()

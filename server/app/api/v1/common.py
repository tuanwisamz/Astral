from app.core.errors import ApiError


def parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    try:
        min_lng, min_lat, max_lng, max_lat = (float(v) for v in bbox.split(","))
    except ValueError as exc:
        raise ApiError(422, "VALIDATION_ERROR", "bbox must be minLng,minLat,maxLng,maxLat") from exc
    if min_lng >= max_lng or min_lat >= max_lat:
        raise ApiError(422, "VALIDATION_ERROR", "bbox min values must be below max values")
    return min_lng, min_lat, max_lng, max_lat


def csv_param(value: str | None) -> set[str] | None:
    return {v.strip().upper() for v in value.split(",") if v.strip()} if value else None

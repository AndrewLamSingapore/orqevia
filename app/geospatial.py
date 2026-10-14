"""Deterministic geospatial primitives for ORQEVIA.

WGS84 geodetic math and a simple lat/lon spatial index. The module is pure
Python and has no network or external dependencies. Coordinates are always
(latitude, longitude) in degrees unless a parameter is explicitly named
``lon``/``lat``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

EARTH_RADIUS_KM = 6371.0088


def validate_latitude(lat: float) -> float:
    if not isinstance(lat, (int, float)) or math.isnan(lat) or math.isinf(lat):
        raise ValueError("latitude must be a finite number")
    if lat < -90.0 or lat > 90.0:
        raise ValueError("latitude out of range [-90, 90]")
    return float(lat)


def validate_longitude(lon: float) -> float:
    if not isinstance(lon, (int, float)) or math.isnan(lon) or math.isinf(lon):
        raise ValueError("longitude must be a finite number")
    if lon < -180.0 or lon > 180.0:
        raise ValueError("longitude out of range [-180, 180]")
    return float(lon)


def validate_coordinate(lat: float, lon: float) -> tuple[float, float]:
    """Return a validated ``(lat, lon)`` pair, rejecting order/range errors."""
    return validate_latitude(lat), validate_longitude(lon)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1, lon1 = validate_coordinate(lat1, lon1)
    lat2, lon2 = validate_coordinate(lat2, lon2)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def normalize_lon(lon: float) -> float:
    lon = float(lon)
    lon = (lon + 180.0) % 360.0 - 180.0
    return lon if lon != -180.0 else 180.0


@dataclass(frozen=True)
class BoundingBox:
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float

    def contains(self, lat: float, lon: float) -> bool:
        lat, lon = validate_coordinate(lat, lon)
        if not (self.min_lat <= lat <= self.max_lat):
            return False
        if self.min_lon <= self.max_lon:
            return self.min_lon <= lon <= self.max_lon
        # Antimeridian-spanning box.
        return lon >= self.min_lon or lon <= self.max_lon


def bounding_box(lat: float, lon: float, radius_km: float) -> list[BoundingBox]:
    """Return one or two bounding boxes for a radius search.

    A radius that crosses the antimeridian is split so consumers never have to
    special-case the wrap themselves.
    """
    lat, lon = validate_coordinate(lat, lon)
    if radius_km < 0 or math.isnan(radius_km) or math.isinf(radius_km):
        raise ValueError("radius_km must be a finite non-negative number")
    radius_km = float(radius_km)
    angular = radius_km / EARTH_RADIUS_KM
    dlat = math.degrees(angular)
    dlon = math.degrees(angular) / max(0.0001, math.cos(math.radians(lat)))
    min_lat = max(-90.0, lat - dlat)
    max_lat = min(90.0, lat + dlat)
    min_lon = normalize_lon(lon - dlon)
    max_lon = normalize_lon(lon + dlon)
    if min_lon <= max_lon:
        return [BoundingBox(min_lat, max_lat, min_lon, max_lon)]
    return [
        BoundingBox(min_lat, max_lat, min_lon, 180.0),
        BoundingBox(min_lat, max_lat, -180.0, max_lon),
    ]


def point_in_polygon(lat: float, lon: float, ring: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon on a closed WGS84 ring (lat, lon)."""
    lat, lon = validate_coordinate(lat, lon)
    if len(ring) < 3:
        raise ValueError("polygon ring requires at least three vertices")
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        yi, xi = validate_coordinate(*ring[i])
        yj, xj = validate_coordinate(*ring[j])
        if (yi > lat) != (yj > lat):
            x_intersect = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if x_intersect == lon:
                return True
            if x_intersect > lon:
                inside = not inside
        j = i
    return inside


class SpatialGridIndex:
    """Lat/lon grid index with geodesic distance, not Euclidean approximation."""

    def __init__(self, cell_degrees: float = 5.0) -> None:
        if cell_degrees <= 0:
            raise ValueError("cell_degrees must be positive")
        self.cell_degrees = float(cell_degrees)
        self.cells: dict[tuple[int, int], dict[str, tuple[float, float]]] = {}

    @staticmethod
    def _cell(lat: float, lon: float, size: float) -> tuple[int, int]:
        return int(math.floor(lat / size)), int(math.floor(lon / size))

    def add(self, key: str, lat: float, lon: float) -> None:
        lat, lon = validate_coordinate(lat, lon)
        self.cells.setdefault(self._cell(lat, lon, self.cell_degrees), {})[key] = (lat, lon)

    def remove(self, key: str, lat: float, lon: float) -> None:
        lat, lon = validate_coordinate(lat, lon)
        cell = self.cells.get(self._cell(lat, lon, self.cell_degrees), {})
        cell.pop(key, None)

    def radius(self, lat: float, lon: float, radius_km: float) -> list[tuple[str, float]]:
        lat, lon = validate_coordinate(lat, lon)
        results: list[tuple[str, float]] = []
        for box in bounding_box(lat, lon, radius_km):
            lat_start, lat_end = sorted((box.min_lat, box.max_lat))
            lon_start, lon_end = sorted((box.min_lon, box.max_lon))
            for cell_lat in range(self._cell(lat_start, 0, self.cell_degrees)[0],
                                  self._cell(lat_end, 0, self.cell_degrees)[0] + 1):
                for cell_lon in range(self._cell(0, lon_start, self.cell_degrees)[1],
                                      self._cell(0, lon_end, self.cell_degrees)[1] + 1):
                    for key, (plat, plon) in self.cells.get((cell_lat, cell_lon), {}).items():
                        dist = haversine_km(lat, lon, plat, plon)
                        if dist <= radius_km:
                            results.append((key, dist))
        return sorted(results, key=lambda pair: pair[1])

    def nearest(self, lat: float, lon: float, k: int = 1) -> list[tuple[str, float]]:
        if k < 1:
            raise ValueError("k must be positive")
        scored: list[tuple[str, float]] = []
        for points in self.cells.values():
            for key, (plat, plon) in points.items():
                scored.append((key, haversine_km(lat, lon, plat, plon)))
        return sorted(scored, key=lambda pair: pair[1])[:k]


def validate_geojson_geometry(geometry: dict) -> dict:
    """Validate the small GeoJSON subset ORQEVIA ingests (Point/Polygon)."""
    if not isinstance(geometry, dict):
        raise ValueError("geometry must be a mapping")
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Point":
        if not isinstance(coords, list) or len(coords) < 2:
            raise ValueError("Point requires [lon, lat]")
        lon, lat = coords[0], coords[1]
        validate_coordinate(lat, lon)
        return {"type": "Point", "coordinates": [float(lon), float(lat)]}
    if gtype == "Polygon":
        if not isinstance(coords, list) or not coords or not isinstance(coords[0], list):
            raise ValueError("Polygon requires a ring of [lon, lat] pairs")
        ring: list[tuple[float, float]] = []
        for pair in coords[0]:
            if not isinstance(pair, list) or len(pair) < 2:
                raise ValueError("invalid polygon vertex")
            ring.append(validate_coordinate(float(pair[1]), float(pair[0])))
        if len(ring) < 3:
            raise ValueError("polygon requires at least three vertices")
        return {"type": "Polygon", "coordinates": [[[lon, lat] for lat, lon in ring]]}
    raise ValueError(f"unsupported geometry type: {gtype!r}")


def parse_latlon(value: str, *, lon_first: bool) -> tuple[float, float]:
    """Parse ``lat,lon`` (default) or ``lon,lat`` text into ``(lat, lon)``."""
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 2:
        raise ValueError("coordinate must be two comma-separated numbers")
    try:
        first, second = float(parts[0]), float(parts[1])
    except ValueError as exc:
        raise ValueError("coordinate values must be numeric") from exc
    if lon_first:
        return validate_coordinate(second, first)
    return validate_coordinate(first, second)

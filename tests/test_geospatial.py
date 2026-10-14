import math

import pytest

from app.geospatial import (
    SpatialGridIndex,
    bounding_box,
    haversine_km,
    parse_latlon,
    point_in_polygon,
    validate_coordinate,
    validate_geojson_geometry,
)


def test_haversine_known_distance():
    # Singapore to Kuala Lumpur is about 312-330 km depending on points used.
    dist = haversine_km(1.3521, 103.8198, 3.1390, 101.6869)
    assert 300 <= dist <= 330


def test_coordinate_validation_rejects_bad_order_and_range():
    with pytest.raises(ValueError):
        validate_coordinate(95.0, 103.0)
    with pytest.raises(ValueError):
        validate_coordinate(1.3, 181.0)


def test_parse_latlon_explicit_order():
    assert parse_latlon("1.35,103.82", lon_first=False) == (1.35, 103.82)
    assert parse_latlon("103.82,1.35", lon_first=True) == (1.35, 103.82)


def test_point_in_polygon_and_antimeridian_box():
    square = [(-1.0, 100.0), (-1.0, 110.0), (1.0, 110.0), (1.0, 100.0)]
    assert point_in_polygon(0.0, 105.0, square) is True
    assert point_in_polygon(2.0, 105.0, square) is False
    boxes = bounding_box(0.0, 179.9, 100.0)
    assert len(boxes) == 2


def test_spatial_index_uses_geodesic_distance():
    index = SpatialGridIndex(cell_degrees=5.0)
    index.add("sg", 1.3521, 103.8198)
    index.add("kl", 3.1390, 101.6869)
    key, dist = index.nearest(1.30, 103.80, k=1)[0]
    assert key == "sg"
    assert dist < haversine_km(1.30, 103.80, 3.1390, 101.6869)


def test_validate_geojson_geometry_point():
    geom = validate_geojson_geometry({"type": "Point", "coordinates": [103.8, 1.3]})
    assert geom["coordinates"] == [103.8, 1.3]

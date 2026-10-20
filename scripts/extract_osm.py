"""T1.1: one pass over the Geofabrik extract → GeoParquet files in data/raw/.

Keeps every road in the pilot areas, and elsewhere only routes with a federal, state or
expressway ref plus major roads (spec §4 "Data depth"). Also extracts admin boundaries,
critical facilities (hospitals, schools, fire stations) and tree features for T1.6, and
university campuses in the pilots, whose internal roads are private (plan §3 Q2).
"""

import re
import time

import geopandas as gpd
import osmium
from shapely import wkb
from shapely.geometry import Point

from common import MAJOR_HIGHWAYS, PBF, PENINSULA_BBOX, RAW, ROAD_HIGHWAYS, WGS84, in_box, in_pilot

ROUTE_REF = re.compile(r"(^|;)\s*(FT\s*)?\d+[A-Z]?\s*($|;)|(^|;)\s*[ABCDJKMNPRTE]\s*\d+", re.I)
CRITICAL = {"hospital", "school", "fire_station"}
TREE_AREAS = {("natural", "wood"), ("landuse", "forest")}

wkbf = osmium.geom.WKBFactory()


def main() -> None:
    roads, bounds, facilities, trees, campuses = [], [], [], [], []
    started = time.time()
    proc = (
        osmium.FileProcessor(str(PBF))
        .with_locations()
        .with_areas(osmium.filter.TagFilter(("boundary", "administrative"), ("natural", "wood"),
                                            ("landuse", "forest"), ("amenity", "hospital"),
                                            ("amenity", "school"), ("amenity", "university")))
    )
    for obj in proc:
        tags = obj.tags
        try:
            if obj.is_node():
                lon, lat = obj.location.lon, obj.location.lat
                if not in_box(lon, lat, PENINSULA_BBOX):
                    continue
                if tags.get("amenity") in CRITICAL:
                    facilities.append({"kind": tags["amenity"], "name": tags.get("name"), "geometry": Point(lon, lat)})
                elif tags.get("natural") == "tree" and in_pilot(lon, lat):
                    trees.append({"kind": "tree", "geometry": Point(lon, lat)})

            elif obj.is_way():
                hw = tags.get("highway")
                if hw in ROAD_HIGHWAYS:
                    first = obj.nodes[0].location
                    if not in_box(first.lon, first.lat, PENINSULA_BBOX):
                        continue
                    ref = tags.get("ref")
                    pilot = in_pilot(first.lon, first.lat)
                    if hw == "service" and not tags.get("name"):
                        continue  # parking aisles and driveways
                    if tags.get("access") in ("private", "no") and not ref:
                        continue  # gated and private roads: neither JKR nor a council maintains them
                    if not pilot and not (ref and ROUTE_REF.search(ref)) and hw not in MAJOR_HIGHWAYS:
                        continue
                    roads.append({
                        "osm_id": obj.id, "highway": hw, "ref": ref, "name": tags.get("name"),
                        "operator": tags.get("operator"), "surface": tags.get("surface"),
                        "lanes": tags.get("lanes"), "oneway": tags.get("oneway"),
                        "geometry": wkb.loads(wkbf.create_linestring(obj), hex=True),
                    })
                elif tags.get("natural") == "tree_row":
                    first = obj.nodes[0].location
                    if in_pilot(first.lon, first.lat):
                        trees.append({"kind": "tree_row", "geometry": wkb.loads(wkbf.create_linestring(obj), hex=True)})

            elif obj.is_area():
                if tags.get("boundary") == "administrative" and tags.get("admin_level") in {"4", "5", "6", "7", "8"}:
                    geom = wkb.loads(wkbf.create_multipolygon(obj), hex=True)
                    c = geom.representative_point()
                    if in_box(c.x, c.y, PENINSULA_BBOX):
                        bounds.append({
                            "osm_id": obj.orig_id(), "from_way": obj.from_way(), "admin_level": int(tags["admin_level"]),
                            "name": tags.get("name"), "name_en": tags.get("name:en"), "name_ms": tags.get("name:ms"),
                            "ref": tags.get("ref"), "iso": tags.get("ISO3166-2"), "geometry": geom,
                        })
                elif tags.get("amenity") == "university":
                    geom = wkb.loads(wkbf.create_multipolygon(obj), hex=True)
                    c = geom.representative_point()
                    if in_pilot(c.x, c.y):
                        campuses.append({"name": tags.get("name"), "geometry": geom})
                elif (tags.get("amenity") in CRITICAL):
                    geom = wkb.loads(wkbf.create_multipolygon(obj), hex=True).representative_point()
                    if in_box(geom.x, geom.y, PENINSULA_BBOX):
                        facilities.append({"kind": tags["amenity"], "name": tags.get("name"), "geometry": geom})
                elif any(tags.get(k) == v for k, v in TREE_AREAS):
                    geom = wkb.loads(wkbf.create_multipolygon(obj), hex=True)
                    c = geom.representative_point()
                    if in_pilot(c.x, c.y):
                        trees.append({"kind": "wood", "geometry": geom})
        except (osmium.InvalidLocationError, RuntimeError):
            continue  # incomplete geometry at the extract's edge

    for name, rows in (("roads", roads), ("boundaries", bounds), ("facilities", facilities), ("trees", trees),
                       ("campuses", campuses)):
        gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=WGS84)
        gdf.to_parquet(RAW / f"{name}.parquet")
        print(f"{name:11s} {len(gdf):>8,d} rows")
    print(f"done in {time.time() - started:.0f} s")


if __name__ == "__main__":
    main()

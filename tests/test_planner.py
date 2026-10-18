from rslib.models import BBox
from rslib.planner import plan_coverage


def feature(id, bounds, cloud):
    w, s, e, n = bounds
    return {
        "id": id,
        "collection": "test",
        "properties": {"eo:cloud_cover": cloud},
        "geometry": {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]},
    }


def test_greedy_planner_prefers_clearer_cover_and_reports_gaps():
    bbox = BBox(west=0, south=0, east=2, north=2)
    items = [
        feature("cloudy-full", (0, 0, 2, 2), 99),
        feature("west", (0, 0, 1, 2), 1),
        feature("east", (1, 0, 2, 2), 1),
    ]
    result = plan_coverage(items, bbox)
    assert [s["id"] for s in result["selected"]] == ["west", "east"]
    assert result["target_reached"] and result["sampled_footprint_coverage"] == 1
    assert not plan_coverage(items[1:2], bbox)["target_reached"]

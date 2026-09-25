"""Geography for the risk globe: the ports in the shipment data, a network of
sea-lane waypoints through the main chokepoints, and routes found on it.

Sea routes take the shortest path over the waypoint network, so a Shanghai to
Rotterdam sailing passes Malacca, Bab-el-Mandeb and Suez as real ones do.
Air routes fly the great circle. Road and rail follow land corridors where the
ports share a landmass; anything else is drawn as a direct line. Place
descriptions are general, well-known facts. Hotspot risk levels come from the
consignments passing them, and each hotspot carries the real GPR index reading
for the country beside it.
"""
from __future__ import annotations

import heapq
import math
from functools import lru_cache

from . import datasets

# name -> (lat, lng, country, description)
PORTS: dict[str, tuple[float, float, str, str]] = {
    "Busan": (35.10, 129.04, "South Korea", "South Korea's largest port and a major Northeast Asian transshipment hub."),
    "Shanghai": (31.23, 121.47, "China", "The world's busiest container port by volume, at the mouth of the Yangtze."),
    "Singapore": (1.26, 103.84, "Singapore", "A leading transshipment hub at the southern end of the Strait of Malacca."),
    "Dubai": (25.01, 55.06, "United Arab Emirates", "Jebel Ali, Dubai's deep-water port and the largest container port in the Middle East."),
    "Rotterdam": (51.95, 4.14, "Netherlands", "Europe's largest port, at the mouth of the Rhine and Meuse."),
    "Antwerp": (51.26, 4.40, "Belgium", "Europe's second largest port, on the river Scheldt."),
    "Hamburg": (53.54, 9.97, "Germany", "Germany's largest port, on the river Elbe about 100 km from the North Sea."),
    "Marseille": (43.33, 5.34, "France", "France's largest port and the main Mediterranean gateway to Western Europe."),
    "Los Angeles": (33.74, -118.27, "United States", "Together with Long Beach, the busiest container port complex in the United States."),
}

# Sea-lane waypoints (lat, lng). Ports are nodes too.
NODES: dict[str, tuple[float, float]] = {
    **{k: (v[0], v[1]) for k, v in PORTS.items()},
    "korea_strait": (34.0, 128.6), "east_china_sea": (29.5, 124.5), "taiwan_strait": (24.2, 119.6),
    "luzon_strait": (20.6, 121.2), "south_china_sea": (11.5, 111.5), "singapore_strait": (1.25, 104.4),
    "malacca": (3.6, 99.6), "andaman": (6.2, 93.5), "dondra": (5.6, 80.8), "arabian_sea": (13.5, 62.0),
    "gulf_of_oman": (24.3, 58.6), "hormuz": (26.5, 56.3), "gulf_of_aden": (12.3, 46.5), "bab_el_mandeb": (12.6, 43.4),
    "red_sea": (20.5, 38.4), "suez": (30.2, 32.55), "port_said": (31.6, 32.3), "east_med": (34.2, 25.5),
    "central_med": (37.4, 11.5), "gulf_of_lion": (42.3, 5.0), "gibraltar": (36.0, -5.6), "portugal": (39.0, -10.2),
    "biscay": (45.5, -8.5), "ushant": (48.6, -5.8), "channel": (50.3, -0.8), "dover": (51.05, 1.6),
    "north_sea": (53.4, 4.2), "elbe_mouth": (53.95, 8.4), "scheldt": (51.42, 3.55),
    "pacific_w": (33.5, 145.0), "pacific_m": (38.5, -178.0), "pacific_e": (35.5, -138.0),
    "baja": (24.5, -113.0), "mexico_pac": (15.5, -100.0), "panama_pac": (7.8, -79.6), "panama": (9.1, -79.7),
    "panama_atl": (10.5, -79.4), "caribbean": (16.5, -74.5), "atlantic_w": (27.0, -62.0), "atlantic_m": (38.0, -38.0),
    "atlantic_e": (45.0, -16.0),
}
EDGES = [
    ("Busan", "korea_strait"), ("korea_strait", "east_china_sea"), ("Shanghai", "east_china_sea"),
    ("east_china_sea", "taiwan_strait"), ("taiwan_strait", "south_china_sea"), ("east_china_sea", "luzon_strait"),
    ("luzon_strait", "south_china_sea"), ("south_china_sea", "singapore_strait"), ("singapore_strait", "Singapore"),
    ("Singapore", "malacca"), ("malacca", "andaman"), ("andaman", "dondra"), ("dondra", "arabian_sea"),
    ("arabian_sea", "gulf_of_oman"), ("gulf_of_oman", "hormuz"), ("hormuz", "Dubai"),
    ("arabian_sea", "gulf_of_aden"), ("gulf_of_aden", "bab_el_mandeb"), ("bab_el_mandeb", "red_sea"),
    ("red_sea", "suez"), ("suez", "port_said"), ("port_said", "east_med"), ("east_med", "central_med"),
    ("central_med", "gulf_of_lion"), ("gulf_of_lion", "Marseille"), ("central_med", "gibraltar"),
    ("gibraltar", "portugal"), ("portugal", "biscay"), ("biscay", "ushant"), ("ushant", "channel"), ("channel", "dover"),
    ("dover", "scheldt"), ("scheldt", "Antwerp"), ("dover", "Rotterdam"), ("dover", "north_sea"), ("north_sea", "Rotterdam"),
    ("north_sea", "elbe_mouth"), ("elbe_mouth", "Hamburg"),
    ("Busan", "pacific_w"), ("east_china_sea", "pacific_w"), ("luzon_strait", "pacific_w"), ("pacific_w", "pacific_m"),
    ("pacific_m", "pacific_e"), ("pacific_e", "Los Angeles"),
    ("Los Angeles", "baja"), ("baja", "mexico_pac"), ("mexico_pac", "panama_pac"), ("panama_pac", "panama"),
    ("panama", "panama_atl"), ("panama_atl", "caribbean"), ("caribbean", "atlantic_w"), ("atlantic_w", "atlantic_m"),
    ("atlantic_m", "atlantic_e"), ("atlantic_e", "ushant"), ("atlantic_e", "portugal"),
]
# Land corridors for road and rail, as interior waypoints.
LAND = {
    frozenset({"Shanghai", "Singapore"}): [(28.2, 113.0), (25.0, 102.7), (18.0, 102.6), (13.75, 100.5), (6.5, 100.4), (3.1, 101.7)],
    frozenset({"Rotterdam", "Hamburg"}): [(52.3, 6.9), (53.1, 8.8)],
    frozenset({"Antwerp", "Hamburg"}): [(51.2, 6.8), (52.4, 9.7)],
    frozenset({"Antwerp", "Rotterdam"}): [(51.6, 4.4)],
    frozenset({"Antwerp", "Marseille"}): [(49.2, 4.0), (47.3, 5.0), (45.8, 4.8)],
    frozenset({"Rotterdam", "Marseille"}): [(50.6, 5.6), (48.7, 6.2), (45.8, 4.8)],
    frozenset({"Hamburg", "Marseille"}): [(50.1, 8.7), (47.6, 7.6), (45.8, 4.8)],
}

# Chokepoints and risk areas. `factor` names the consignment input that sets the hotspot's level;
# `gpr` names the country whose real GPR reading is shown beside it.
HOTSPOTS = [
    {"id": "taiwan", "name": "Taiwan Strait", "lat": 24.2, "lng": 119.6, "factor": "geopolitical_risk_index", "gpr": "TWN",
     "about": "The 180 km strait between Taiwan and mainland China, carrying much of East Asia's container traffic."},
    {"id": "malacca", "name": "Strait of Malacca", "lat": 3.6, "lng": 99.6, "factor": "geopolitical_risk_index", "gpr": "MYS",
     "about": "The main sea link between the Indian Ocean and the Pacific, and one of the busiest shipping lanes in the world."},
    {"id": "hormuz", "name": "Strait of Hormuz", "lat": 26.5, "lng": 56.3, "factor": "geopolitical_risk_index", "gpr": "SAU",
     "about": "The strait between the Persian Gulf and the Gulf of Oman, one of the world's most important oil chokepoints."},
    {"id": "arabian_sea", "name": "Arabian Sea", "lat": 13.5, "lng": 62.0, "factor": "weather_risk_index", "gpr": None,
     "about": "Open-water leg with heavy swell during the southwest monsoon and cyclones either side of it."},
    {"id": "bab_el_mandeb", "name": "Bab-el-Mandeb", "lat": 12.6, "lng": 43.4, "factor": "geopolitical_risk_index", "gpr": "EGY",
     "about": "The narrow strait between Yemen and the Horn of Africa that links the Red Sea to the Gulf of Aden."},
    {"id": "suez", "name": "Suez Canal", "lat": 30.2, "lng": 32.55, "factor": "geopolitical_risk_index", "gpr": "EGY",
     "about": "The canal linking the Mediterranean to the Red Sea, the shortest sea route between Asia and Europe."},
    {"id": "gibraltar", "name": "Strait of Gibraltar", "lat": 36.0, "lng": -5.6, "factor": "weather_risk_index", "gpr": "ESP",
     "about": "The 14 km gateway between the Atlantic and the Mediterranean."},
    {"id": "channel", "name": "English Channel", "lat": 50.3, "lng": -0.8, "factor": "weather_risk_index", "gpr": "GBR",
     "about": "One of the busiest shipping lanes in the world, with strict traffic separation and frequent winter gales."},
    {"id": "north_pacific", "name": "North Pacific crossing", "lat": 38.5, "lng": -178.0, "factor": "weather_risk_index", "gpr": None,
     "about": "Long trans-Pacific leg exposed to autumn and winter storm tracks."},
    {"id": "panama", "name": "Panama Canal", "lat": 9.1, "lng": -79.7, "factor": "weather_risk_index", "gpr": None,
     "about": "Lock canal linking the Pacific and Atlantic. Transit slots tighten when lake water levels fall in dry years."},
]
HOTSPOT_RADIUS_KM = 350


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(min(1, math.sqrt(h)))


@lru_cache(maxsize=1)
def _graph() -> dict[str, list[tuple[str, float]]]:
    g: dict[str, list[tuple[str, float]]] = {k: [] for k in NODES}
    for a, b in EDGES:
        d = _km(NODES[a], NODES[b])
        g[a].append((b, d))
        g[b].append((a, d))
    return g


@lru_cache(maxsize=128)
def sea_path(origin: str, destination: str) -> tuple[tuple[float, float], ...] | None:
    """Shortest waypoint path between two ports over the sea-lane network."""
    if origin not in NODES or destination not in NODES:
        return None
    g, dist, prev, heap = _graph(), {origin: 0.0}, {}, [(0.0, origin)]
    while heap:
        d, n = heapq.heappop(heap)
        if n == destination:
            break
        if d > dist.get(n, math.inf):
            continue
        for m, w in g[n]:
            nd = d + w
            if nd < dist.get(m, math.inf):
                dist[m], prev[m] = nd, n
                heapq.heappush(heap, (nd, m))
    if destination not in dist:
        return None
    path, n = [destination], destination
    while n != origin:
        n = prev[n]
        path.append(n)
    return tuple(NODES[p] for p in reversed(path))


def place(name: str | None) -> dict | None:
    if not name or name not in PORTS:
        return None
    lat, lng, country, about = PORTS[name]
    return {"name": name, "lat": lat, "lng": lng, "country": country, "about": about, "gpr": datasets.port_gpr(name)}


def route(rec: dict) -> dict | None:
    """Map geometry for one consignment, or None if its ports are unknown."""
    o, d = place(rec.get("origin_port")), place(rec.get("destination_port"))
    if not o or not d or o["name"] == d["name"]:
        return None
    mode = str(rec.get("mode") or "Sea").lower()
    ends = [(o["lat"], o["lng"]), (d["lat"], d["lng"])]
    air, pts = mode == "air", None
    if mode == "sea":
        pts = sea_path(o["name"], d["name"])
    elif mode in ("road", "rail"):
        interior = LAND.get(frozenset({o["name"], d["name"]}))
        if interior is not None:
            if _km(interior[0], ends[0]) > _km(interior[0], ends[1]):   # corridors are stored in one direction
                interior = interior[::-1]
            pts = [ends[0], *interior, ends[1]]
    if pts is None:
        air, pts = True, ends     # air, or a land mode with no corridor between these ports
    return {"origin": o, "destination": d, "points": [list(p) for p in pts], "air": air}


def geo_payload(results: list[dict]) -> dict:
    routes = {r["consignment_id"]: route(r) for r in results}
    hotspots = []
    for h in HOTSPOTS:
        lanes = [cid for cid, g in routes.items()
                 if g and not g["air"] and min(_km((h["lat"], h["lng"]), tuple(p)) for p in g["points"]) <= HOTSPOT_RADIUS_KM]
        if lanes:
            hotspots.append({**h, "lanes": lanes, "gpr": datasets.gpr_country(h["gpr"]) if h["gpr"] else None})
    return {"routes": {k: v for k, v in routes.items() if v}, "hotspots": hotspots,
            "unmapped": sorted(cid for cid, g in routes.items() if not g)}

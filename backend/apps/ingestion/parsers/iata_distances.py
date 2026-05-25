"""
IATA airport coordinates and haversine distance calculator
==========================================================
Used by the travel parser to convert flight routes (expressed as
IATA origin/destination pairs) into great-circle distances in km,
which are then multiplied by a per-km emission factor to produce
kg CO₂e.

Why a static dict instead of an external API or full airport DB?
-----------------------------------------------------------------
A full airport database (OurAirports CSV, ~7,500 airports) would be
more complete, but adds a file dependency, a loading step, and a
maintenance burden for an assignment prototype. For corporate travel
data, 95% of routes will involve the ~60 airports in this file —
employees at enterprise clients fly between major hubs, not between
regional airstrips. The limitation is documented in SOURCES.md.

If a route involves an unknown airport code, distance_km() returns
None and the parser flags the row for analyst review rather than
silently producing a zero-emission flight.

Coordinate source
-----------------
All lat/lon values are from public aviation databases (OurAirports,
FAA, ICAO). Accuracy is sufficient for great-circle estimation —
we are not routing around the curvature of the Earth or air traffic
corridors, which would add ~5–10% to actual flight distances.

Haversine formula
-----------------
Great-circle distance on a sphere:
    a = sin²(Δlat/2) + cos(lat1) · cos(lat2) · sin²(Δlon/2)
    c = 2 · atan2(√a, √(1−a))
    d = R · c        where R = 6371 km (mean Earth radius)

This slightly underestimates actual flight distances because aircraft
follow wind-optimised routes and must avoid restricted airspace.
DEFRA's emission factors already account for this with a Radiative
Forcing Index (RFI) multiplier of 1.9 baked into the per-km factor,
so we do not apply any additional distance correction here.
"""

import math
from typing import Optional


# ---------------------------------------------------------------------------
# Airport coordinate registry
# (IATA code → (latitude_dd, longitude_dd))
# Format: positive = N / E, negative = S / W
# ---------------------------------------------------------------------------

AIRPORTS: dict[str, tuple[float, float]] = {

    # ── India ──────────────────────────────────────────────────────────────
    "BOM": (19.0896,  72.8656),   # Mumbai Chhatrapati Shivaji
    "DEL": (28.5665,  77.1031),   # Delhi Indira Gandhi
    "BLR": (13.1986,  77.7066),   # Bengaluru Kempegowda
    "MAA": (12.9900,  80.1693),   # Chennai
    "HYD": (17.2403,  78.4294),   # Hyderabad Rajiv Gandhi
    "CCU": (22.6547,  88.4467),   # Kolkata Netaji Subhas
    "AMD": (23.0772,  72.6347),   # Ahmedabad Sardar Vallabhbhai
    "PNQ": (18.5822,  73.9197),   # Pune
    "GOI": (15.3808,  73.8314),   # Goa Dabolim
    "COK": (10.1520,  76.4019),   # Kochi
    "TRV": ( 8.4782,  76.9201),   # Thiruvananthapuram
    "IXC": (30.6735,  76.7885),   # Chandigarh

    # ── Middle East ────────────────────────────────────────────────────────
    "DXB": (25.2532,  55.3657),   # Dubai International
    "AUH": (24.4330,  54.6511),   # Abu Dhabi
    "DOH": (25.2731,  51.6081),   # Doha Hamad
    "RUH": (24.9578,  46.6989),   # Riyadh King Khalid
    "BAH": (26.2708,  50.6336),   # Bahrain
    "AMM": (31.7226,  35.9932),   # Amman Queen Alia
    "BEY": (33.8209,  35.4883),   # Beirut Rafic Hariri

    # ── Europe — Western ──────────────────────────────────────────────────
    "LHR": (51.4775,  -0.4614),   # London Heathrow
    "LGW": (51.1537,  -0.1821),   # London Gatwick
    "CDG": (49.0097,   2.5479),   # Paris Charles de Gaulle
    "AMS": (52.3086,   4.7639),   # Amsterdam Schiphol
    "FRA": (50.0379,   8.5622),   # Frankfurt
    "MUC": (48.3537,  11.7750),   # Munich
    "ZRH": (47.4647,   8.5492),   # Zurich
    "VIE": (48.1103,  16.5697),   # Vienna
    "BRU": (50.9014,   4.4844),   # Brussels
    "GVA": (46.2381,   6.1089),   # Geneva
    "ARN": (59.6519,  17.9186),   # Stockholm Arlanda
    "CPH": (55.6180,  12.6561),   # Copenhagen
    "OSL": (60.1939,  11.1004),   # Oslo Gardermoen
    "HEL": (60.3172,  24.9633),   # Helsinki
    "DUB": (53.4213,  -6.2700),   # Dublin
    "LIS": (38.7756,  -9.1354),   # Lisbon
    "MAD": (40.4936,  -3.5668),   # Madrid Barajas
    "BCN": (41.2971,   2.0785),   # Barcelona
    "MXP": (45.6306,   8.7281),   # Milan Malpensa
    "FCO": (41.8003,  12.2389),   # Rome Fiumicino
    "WAW": (52.1657,  20.9671),   # Warsaw Chopin

    # ── Europe — Eastern ──────────────────────────────────────────────────
    "IST": (41.2753,  28.7519),   # Istanbul
    "SVO": (55.9726,  37.4146),   # Moscow Sheremetyevo
    "LED": (59.8003,  30.2625),   # St. Petersburg Pulkovo

    # ── Asia Pacific ──────────────────────────────────────────────────────
    "SIN": ( 1.3644, 103.9915),   # Singapore Changi
    "HKG": (22.3080, 113.9185),   # Hong Kong
    "PEK": (40.0799, 116.6031),   # Beijing Capital
    "PVG": (31.1443, 121.8083),   # Shanghai Pudong
    "NRT": (35.7720, 140.3929),   # Tokyo Narita
    "HND": (35.5494, 139.7798),   # Tokyo Haneda
    "ICN": (37.4602, 126.4407),   # Seoul Incheon
    "BKK": (13.6811, 100.7475),   # Bangkok Suvarnabhumi
    "KUL": ( 2.7456, 101.7072),   # Kuala Lumpur
    "CGK": (-6.1256, 106.6558),   # Jakarta Soekarno-Hatta
    "SYD": (-33.9399, 151.1753),  # Sydney
    "MEL": (-37.6690, 144.8410),  # Melbourne
    "MNL": (14.5086, 121.0194),   # Manila Ninoy Aquino
    "TPE": (25.0777, 121.2328),   # Taipei Taoyuan

    # ── North America ─────────────────────────────────────────────────────
    "JFK": (40.6413, -73.7781),   # New York JFK
    "EWR": (40.6895, -74.1745),   # New York Newark
    "LGA": (40.7769, -73.8740),   # New York LaGuardia
    "ORD": (41.9742, -87.9073),   # Chicago O'Hare
    "LAX": (33.9425, -118.4081),  # Los Angeles
    "SFO": (37.6213, -122.3790),  # San Francisco
    "BOS": (42.3656, -71.0096),   # Boston Logan
    "IAD": (38.9531, -77.4565),   # Washington Dulles
    "DFW": (32.8998, -97.0403),   # Dallas Fort Worth
    "MIA": (25.7959, -80.2870),   # Miami
    "SEA": (47.4502, -122.3088),  # Seattle-Tacoma
    "ATL": (33.6407, -84.4277),   # Atlanta Hartsfield
    "YYZ": (43.6772, -79.6306),   # Toronto Pearson
    "YVR": (49.1967, -123.1815),  # Vancouver
    "MEX": (19.4363, -99.0721),   # Mexico City

    # ── Africa ────────────────────────────────────────────────────────────
    "JNB": (-26.1392,  28.2460),  # Johannesburg OR Tambo
    "CPT": (-33.9715,  18.6021),  # Cape Town
    "NBO": ( -1.3192,  36.9275),  # Nairobi Jomo Kenyatta
    "CAI": (30.1219,  31.4056),   # Cairo
    "LOS": ( 6.5774,   3.3213),   # Lagos Murtala Muhammed
    "ADD": ( 8.9779,  38.7993),   # Addis Ababa Bole

    # ── South America ─────────────────────────────────────────────────────
    "GRU": (-23.4356, -46.4731),  # São Paulo Guarulhos
    "EZE": (-34.8222, -58.5358),  # Buenos Aires Ezeiza
    "BOG": ( 4.7016,  -74.1469),  # Bogotá El Dorado
    "LIM": (-12.0219, -77.1143),  # Lima Jorge Chávez
    "SCL": (-33.3930, -70.7858),  # Santiago
}


# ---------------------------------------------------------------------------
# Haversine distance
# ---------------------------------------------------------------------------

EARTH_RADIUS_KM = 6371.0


def distance_km(
    origin: str,
    destination: str,
) -> Optional[float]:
    """
    Return the great-circle distance in km between two IATA airports.

    Returns None (not 0) if either code is unknown so the caller can
    distinguish "unknown route" from "zero-distance route" (same airport).

    Args:
        origin:      IATA code, case-insensitive  (e.g. "BOM", "bom")
        destination: IATA code, case-insensitive  (e.g. "LHR")

    Returns:
        Distance in km as a float, or None if either code is not found.

    Examples:
        >>> distance_km("FRA", "LHR")
        654.1
        >>> distance_km("BOM", "DEL")
        1150.7
        >>> distance_km("FRA", "SIN")
        10217.6
        >>> distance_km("XXX", "LHR")
        None
    """
    iata_a = origin.strip().upper()
    iata_b = destination.strip().upper()

    coords_a = AIRPORTS.get(iata_a)
    coords_b = AIRPORTS.get(iata_b)

    if coords_a is None or coords_b is None:
        return None

    if iata_a == iata_b:
        return 0.0

    return _haversine(coords_a[0], coords_a[1], coords_b[0], coords_b[1])


def unknown_airports(origin: str, destination: str) -> list[str]:
    """
    Return a list of codes from the pair that are not in the registry.
    Empty list means both are known.
    Used by the travel parser to build a specific flag_reason message.
    """
    unknown = []
    for code in (origin.strip().upper(), destination.strip().upper()):
        if code and code not in AIRPORTS:
            unknown.append(code)
    return unknown


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Core haversine formula. All inputs in decimal degrees.
    Returns distance in km.

    Derivation:
        Convert degrees to radians.
        a = sin²(Δlat/2) + cos(lat1)·cos(lat2)·sin²(Δlon/2)
        c = 2·atan2(√a, √(1−a))
        d = R·c

    This is numerically stable for both antipodal points (opposite
    sides of the Earth, a→1) and co-located points (a→0).
    """
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlat_r = math.radians(lat2 - lat1)
    dlon_r = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat_r / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon_r / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(EARTH_RADIUS_KM * c, 1)


# ---------------------------------------------------------------------------
# Convenience: batch lookup for a list of (origin, dest) pairs
# ---------------------------------------------------------------------------

def batch_distances(routes: list[tuple[str, str]]) -> dict[tuple[str, str], Optional[float]]:
    """
    Return a dict mapping (origin, dest) → distance_km for a list of routes.
    Useful for pre-computing distances during testing or migration scripts.

    Example:
        routes = [("BOM", "LHR"), ("FRA", "JFK"), ("DEL", "SIN")]
        results = batch_distances(routes)
        # {("BOM", "LHR"): 7193.2, ({"FRA", "JFK"): 6197.8, ...}
    """
    return {
        (o, d): distance_km(o, d) for o, d in routes
    }


# ---------------------------------------------------------------------------
# Self-test — run directly to verify key routes
# python -m apps.ingestion.parsers.iata_distances
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    REFERENCE_ROUTES = [
        # (origin, dest, expected_km_approx, description)
        ("FRA", "LHR",   654,  "Frankfurt → London (short-haul Europe)"),
        ("BOM", "DEL",  1150,  "Mumbai → Delhi (domestic India)"),
        ("BOM", "LHR",  7193,  "Mumbai → London (long-haul)"),
        ("FRA", "SIN", 10218,  "Frankfurt → Singapore (ultra long-haul)"),
        ("JFK", "LHR",  5540,  "New York → London (transatlantic)"),
        ("SYD", "LHR", 16993,  "Sydney → London (one of the longest routes)"),
        ("DEL", "DXB",  2196,  "Delhi → Dubai (popular India-Gulf route)"),
        ("SIN", "HKG",  2572,  "Singapore → Hong Kong (SE Asia)"),
        ("LAX", "NRT",  8815,  "LA → Tokyo (transpacific)"),
        ("JNB", "LHR",  9073,  "Johannesburg → London (Africa-Europe)"),
    ]

    print(f"\n{'Route':<12} {'Expected':>10} {'Got':>10} {'Δ%':>8}  Description")
    print("─" * 72)
    all_ok = True
    for origin, dest, expected, desc in REFERENCE_ROUTES:
        got = distance_km(origin, dest)
        if got is None:
            print(f"{origin}→{dest:<6} {'expected':>10} {'MISSING':>10}           {desc}")
            all_ok = False
            continue
        delta_pct = abs(got - expected) / expected * 100
        status = "✓" if delta_pct < 3 else "✗"
        print(f"{origin}→{dest:<6} {expected:>10} {got:>10.1f} {delta_pct:>7.1f}%  {status} {desc}")
        if delta_pct >= 3:
            all_ok = False

    print("─" * 72)

    unknown_test = distance_km("XXX", "LHR")
    print(f"\nunknown code test (XXX→LHR): {unknown_test}  {'✓' if unknown_test is None else '✗'}")

    same_airport = distance_km("LHR", "LHR")
    print(f"same airport test (LHR→LHR): {same_airport}  {'✓' if same_airport == 0.0 else '✗'}")

    print(f"\n{'All checks passed ✓' if all_ok else 'Some checks failed ✗'}")
    print(f"Total airports in registry: {len(AIRPORTS)}")

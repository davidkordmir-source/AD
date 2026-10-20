"""Input validation and WGS84 geometry, independent of ArcGIS."""

import math
import re
from dataclasses import dataclass


_TRANSLATE = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩−٫٬", "01234567890123456789-. ")
UNITS = {"m": 1.0, "km": 1000.0, "ft": 0.3048, "mi": 1609.344}
COMPASS = {"N": 0, "NE": 45, "E": 90, "SE": 135,
           "S": 180, "SW": 225, "W": 270, "NW": 315}


def number(value):
    """Parse a finite number; a comma is a decimal mark, never a group mark."""
    if value is None or isinstance(value, bool):
        raise ValueError("مقدار عددی خالی یا نامعتبر است.")
    text = str(value).translate(_TRANSLATE).strip().replace(" ", "").replace(",", ".")
    try:
        result = float(text)
    except (ValueError, TypeError):
        raise ValueError(f"مقدار عددی نامعتبر: {value!r}") from None
    if not math.isfinite(result):
        raise ValueError("مقدار عددی باید متناهی باشد.")
    return result


def _degrees(text):
    text = text.strip()
    # Decimal degrees, optionally followed by a degree sign or 'deg'.
    match = re.fullmatch(r"([+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:e[+-]?\d+)?)\s*(?:°|deg)?", text, re.I)
    if match:
        return number(match[1])
    # DMS requires separators: 123:30:00 or 123°30'00". Two parts mean D:M.
    text = re.sub(r"deg|°|º|[′’']|[″\"]|:", " ", text, flags=re.I)
    parts = text.split()
    if len(parts) not in (2, 3) or not all(re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", p) for p in parts):
        raise ValueError("آزیموت باید عدد، D:M:S، یا جهت مانند N45E باشد.")
    d, m = number(parts[0]), number(parts[1])
    s = number(parts[2]) if len(parts) == 3 else 0.0
    if d != int(d) or not (0 <= m < 60 and 0 <= s < 60):
        raise ValueError("در DMS، درجه صحیح و دقیقه و ثانیه در بازهٔ صفر تا کمتر از ۶۰ باشند.")
    sign = -1 if parts[0].startswith("-") else 1
    return sign * (abs(d) + m / 60 + s / 3600)


def azimuth(value):
    if value is None or isinstance(value, bool):
        raise ValueError("آزیموت خالی یا نامعتبر است.")
    if isinstance(value, (int, float)):
        result = number(value)
        if not 0 <= result <= 360:
            raise ValueError("آزیموت باید بین صفر و ۳۶۰ درجه باشد.")
        return result
    text = str(value).translate(_TRANSLATE).strip().upper()
    if text in COMPASS:
        return float(COMPASS[text])
    quadrant = re.fullmatch(r"([NS])\s*(.+?)\s*([EW])", text)
    if quadrant:
        angle = _degrees(quadrant[2])
        if not 0 <= angle <= 90:
            raise ValueError("زاویهٔ جهت ربع‌دایره‌ای باید بین صفر و ۹۰ باشد.")
        north, east = quadrant[1] == "N", quadrant[3] == "E"
        return ((angle if east else -angle) if north else (180-angle if east else 180+angle)) % 360
    result = _degrees(text)
    if not 0 <= result <= 360:
        raise ValueError("آزیموت باید بین صفر و ۳۶۰ درجه باشد.")
    return result


def angle_ranges(start, end):
    """Clockwise true-north angles. Equal endpoints mean a complete circle."""
    start, end = azimuth(start) % 360, azimuth(end) % 360
    if math.isclose(start, end, abs_tol=1e-10, rel_tol=0):
        return [(0.0, 360.0)]
    if start < end:
        return [(start, end)]
    return [(start, 360.0)] + ([(0.0, end)] if end else [])


def destination(lon, lat, bearing, distance):
    """Vincenty's direct solution on WGS84 (metres, true-north degrees)."""
    if distance == 0:
        return lon, lat
    a, f = 6378137.0, 1 / 298.257223563
    b = (1-f)*a
    alpha = math.radians(bearing)
    tan_u = (1-f)*math.tan(math.radians(lat))
    cos_u = 1 / math.sqrt(1+tan_u*tan_u)
    sin_u = tan_u*cos_u
    sigma1 = math.atan2(tan_u, math.cos(alpha))
    sin_alpha = cos_u*math.sin(alpha)
    cos2_alpha = 1-sin_alpha*sin_alpha
    u2 = cos2_alpha*(a*a-b*b)/(b*b)
    aa = 1+u2/16384*(4096+u2*(-768+u2*(320-175*u2)))
    bb = u2/1024*(256+u2*(-128+u2*(74-47*u2)))
    sigma = distance/(b*aa)
    for _ in range(100):
        cos2sm = math.cos(2*sigma1+sigma)
        sins, coss = math.sin(sigma), math.cos(sigma)
        delta = bb*sins*(cos2sm+bb/4*(coss*(-1+2*cos2sm*cos2sm)
                - bb/6*cos2sm*(-3+4*sins*sins)*(-3+4*cos2sm*cos2sm)))
        updated = distance/(b*aa)+delta
        if abs(updated-sigma) < 1e-12:
            sigma = updated
            break
        sigma = updated
    else:
        raise ValueError("محاسبهٔ مرز ژئودزیک همگرا نشد.")
    sins, coss = math.sin(sigma), math.cos(sigma)
    tmp = sin_u*sins-cos_u*coss*math.cos(alpha)
    lat2 = math.atan2(sin_u*coss+cos_u*sins*math.cos(alpha), (1-f)*math.sqrt(sin_alpha*sin_alpha+tmp*tmp))
    lam = math.atan2(sins*math.sin(alpha), cos_u*coss-sin_u*sins*math.cos(alpha))
    c = f/16*cos2_alpha*(4+f*(4-3*cos2_alpha))
    l = lam-(1-c)*f*sin_alpha*(sigma+c*sins*(math.cos(2*sigma1+sigma)
            +c*coss*(-1+2*math.cos(2*sigma1+sigma)**2)))
    return (lon+math.degrees(l)+180) % 360-180, math.degrees(lat2)


def sector_ring(lon, lat, start, end, radius, cell_size):
    ranges = angle_ranges(start, end)
    full = ranges == [(0.0, 360.0)]
    first = ranges[0][0]
    sweep = sum(b-a for a, b in ranges)
    # Keep chord error <= 1/4 pixel, with no more than one degree per segment.
    tolerance = min(radius, cell_size/4)
    step = min(1.0, math.degrees(2*math.acos(max(-1, 1-tolerance/radius))))
    segments = max(1, math.ceil(sweep/max(step, 1e-5)))
    arc = [destination(lon, lat, first+sweep*i/segments, radius) for i in range(segments+1)]
    if full:
        return arc[:-1]+[arc[0]]
    return [(lon, lat)]+arc+[(lon, lat)]


@dataclass(frozen=True)
class Settings:
    points: str
    dem: str
    start_field: str
    end_field: str
    output_dir: str
    radius: float = 5
    radius_unit: str = "km"
    receiver: float = 2
    receiver_unit: str = "m"
    target: float = 0
    target_unit: str = "m"
    dem_z_unit: str = "m"
    cell_size: float = 0
    output_epsg: int = 0
    refraction: float = 0.13
    polygons: bool = False

    @property
    def radius_m(self):
        return self.radius*UNITS[self.radius_unit]

    def validate(self):
        for field in ("points", "dem", "start_field", "end_field", "output_dir"):
            if not getattr(self, field).strip():
                raise ValueError(f"ورودی الزامی خالی است: {field}")
        for field in ("radius_unit", "receiver_unit", "target_unit", "dem_z_unit"):
            if getattr(self, field) not in UNITS:
                raise ValueError(f"واحد نامعتبر: {field}")
        for field in ("radius", "receiver", "target", "cell_size", "refraction"):
            if not math.isfinite(getattr(self, field)) or getattr(self, field) < 0:
                raise ValueError(f"مقدار نامعتبر: {field}")
        if not 0 < self.radius_m <= 500000:
            raise ValueError("شعاع باید بزرگ‌تر از صفر و حداکثر ۵۰۰ کیلومتر باشد.")
        if not 0 <= self.refraction < 1:
            raise ValueError("ضریب شکست باید از صفر تا کمتر از یک باشد.")
        if self.output_epsg < 0:
            raise ValueError("کد EPSG نامعتبر است.")

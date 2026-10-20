"""Settings and bearing parsing shared by the standalone GUI and engine."""

from dataclasses import dataclass
import math

from sector_viewshed.core import azimuth, angle_ranges, number, UNITS


class Cancelled(Exception):
    pass


@dataclass(frozen=True)
class FastSettings:
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
    resolution_factor: int = 1
    output_epsg: int = 0
    refraction: float = 0.13
    merge_coverage: bool = False
    max_grid_mcells: int = 25
    auto_coarsen: bool = True

    @property
    def radius_m(self):
        return self.radius*UNITS[self.radius_unit]

    def validate(self):
        for name in ("points", "dem", "start_field", "end_field", "output_dir"):
            if not str(getattr(self, name)).strip():
                raise ValueError("ورودی الزامی خالی است: "+name)
        for name in ("radius_unit", "receiver_unit", "target_unit", "dem_z_unit"):
            if getattr(self, name) not in UNITS:
                raise ValueError("واحد نامعتبر: "+name)
        for name in ("radius", "receiver", "target", "cell_size", "refraction"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError("مقدار نامعتبر: "+name)
        if not 0 < self.radius_m <= 300000:
            raise ValueError("شعاع باید بزرگ‌تر از صفر و حداکثر ۳۰۰ کیلومتر باشد.")
        if not 0 <= self.refraction < 1:
            raise ValueError("ضریب شکست باید از صفر تا کمتر از یک باشد.")
        if self.resolution_factor not in (1, 2, 4):
            raise ValueError("ضریب تفکیک نامعتبر است.")
        if self.output_epsg < 0:
            raise ValueError("EPSG نامعتبر است.")
        if isinstance(self.max_grid_mcells, bool) or not isinstance(self.max_grid_mcells, int) or not 1 <= self.max_grid_mcells <= 100:
            raise ValueError("سقف شبکه باید عدد صحیح از ۱ تا ۱۰۰ میلیون سلول باشد.")
        if not isinstance(self.auto_coarsen, bool):
            raise ValueError("تنظیم خودکار پیکسل باید روشن یا خاموش باشد.")

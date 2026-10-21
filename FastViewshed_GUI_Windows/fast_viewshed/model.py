"""Settings and bearing parsing shared by the standalone GUI and engine."""

from dataclasses import dataclass
import math

from sector_viewshed.core import azimuth, angle_ranges, number, UNITS


class Cancelled(Exception):
    pass


@dataclass(frozen=True)
class ObserverRecord:
    row: tuple
    name: str
    observer: float
    receiver: float
    name_fallback: bool = False


@dataclass(frozen=True)
class FastSettings:
    points: str
    dem: str
    start_field: str
    end_field: str
    output_dir: str
    radius: float = 5
    radius_unit: str = "km"
    observer: float = 100
    observer_unit: str = "m"
    receiver: float = 2
    receiver_unit: str = "m"
    dem_z_unit: str = "m"
    cell_size: float = 0
    resolution_factor: int = 1
    output_epsg: int = 0
    atmospheric_factor: float = 1.33333
    merge_coverage: bool = False
    max_grid_mcells: int = 25
    auto_coarsen: bool = True
    curvature_enabled: bool = True
    nodata_policy: str = "unknown"
    observer_fid: int = -1
    observer_field: str = ""
    receiver_field: str = ""
    name_field: str = ""
    separate_outputs: bool = False
    combined_name_field: str = ""
    combined_name_value: str = ""

    @property
    def radius_m(self):
        return self.radius*UNITS[self.radius_unit]

    @property
    def curvature_coefficient(self):
        # Global Mapper's Atmospheric Correction is the effective Earth
        # radius factor k; GDAL expects curvature coefficient 1/k.
        return 1/self.atmospheric_factor if self.curvature_enabled else 0.0

    def validate(self):
        for name in ("points", "dem", "start_field", "end_field", "output_dir"):
            if not str(getattr(self, name)).strip():
                raise ValueError("ورودی الزامی خالی است: "+name)
        for name in ("radius_unit", "observer_unit", "receiver_unit", "dem_z_unit"):
            if getattr(self, name) not in UNITS:
                raise ValueError("واحد نامعتبر: "+name)
        for name in ("radius", "observer", "receiver", "cell_size", "atmospheric_factor"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError("مقدار نامعتبر: "+name)
        if not 0 < self.radius_m <= 300000:
            raise ValueError("شعاع باید بزرگ‌تر از صفر و حداکثر ۳۰۰ کیلومتر باشد.")
        if not 0 < self.atmospheric_factor <= 1000:
            raise ValueError("ضریب Atmospheric Correction باید مثبت و حداکثر ۱۰۰۰ باشد.")
        if self.resolution_factor not in (1, 2, 4):
            raise ValueError("ضریب تفکیک نامعتبر است.")
        if self.output_epsg < 0:
            raise ValueError("EPSG نامعتبر است.")
        if isinstance(self.max_grid_mcells, bool) or not isinstance(self.max_grid_mcells, int) or not 1 <= self.max_grid_mcells <= 100:
            raise ValueError("سقف شبکه باید عدد صحیح از ۱ تا ۱۰۰ میلیون سلول باشد.")
        if not isinstance(self.auto_coarsen, bool):
            raise ValueError("تنظیم خودکار پیکسل باید روشن یا خاموش باشد.")
        if not isinstance(self.curvature_enabled, bool):
            raise ValueError("تنظیم انحنای زمین باید روشن یا خاموش باشد.")
        if self.nodata_policy not in ("unknown", "sea_level"):
            raise ValueError("روش برخورد با ارتفاع ناموجود نامعتبر است.")
        if isinstance(self.observer_fid, bool) or not isinstance(self.observer_fid, int) or self.observer_fid < -1:
            raise ValueError("FID باید عدد صحیح از منفی یک به بالا باشد؛ منفی یک یعنی همهٔ نقاط.")
        for field in ("observer_field", "receiver_field", "name_field", "combined_name_field", "combined_name_value"):
            if not isinstance(getattr(self, field), str):
                raise ValueError("نام ستون نامعتبر است: "+field)
        if not isinstance(self.separate_outputs, bool):
            raise ValueError("حالت خروجی جداگانه نامعتبر است.")
        if self.separate_outputs and self.merge_coverage:
            raise ValueError("برای خروجی مستقل هر نقطه، گزینهٔ ادغام پوشش‌ها را خاموش کنید.")

"""Rate-of-rise alarm for lake outbursts and sudden river surges."""

from .detect import DetectorConfig, FixedThreshold, RateOfRiseDetector, Status
from .sampling import AdaptiveSampler, EnergyModel, SamplerConfig
from .travel import Reach, travel_time_h

__all__ = [
    "AdaptiveSampler",
    "DetectorConfig",
    "EnergyModel",
    "FixedThreshold",
    "RateOfRiseDetector",
    "Reach",
    "SamplerConfig",
    "Status",
    "travel_time_h",
]
__version__ = "0.1.0"

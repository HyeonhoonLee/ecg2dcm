"""ECG2DCM: convert resting ECG recordings to DICOM General ECG Waveform Storage."""
__version__ = '1.3.0'

from .ir import EcgRecord, Waveform, Measurements          # noqa: F401
from .writer import build, write, deidentify              # noqa: F401
from .conformance import check_iod_constraints            # noqa: F401
from .adapters.dispatch import parse, sniff, UnsupportedFormatError   # noqa: F401

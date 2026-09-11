"""Vendor-neutral intermediate representation of a resting ECG record.

Every source-format adapter (GE MUSE, GE CardioSoft, Philips, HL7 aECG,
Mortara, Schiller, WFDB) produces an :class:`EcgRecord`; the single writer in
:mod:`ecg2dcm.writer` turns it into a DICOM General ECG Waveform Storage object.
Only the adapters know anything about a source format.

Units are fixed here so that the writer never has to guess: sample values are
signed 16-bit integers scaled by ``units_per_bit`` microvolts, filter edges are
in hertz, intervals in milliseconds, axes in degrees, and fiducial points are
0-based sample positions within the median (representative beat) group.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

LEAD_ORDER = ['I', 'II', 'III', 'aVR', 'aVL', 'aVF',
              'V1', 'V2', 'V3', 'V4', 'V5', 'V6']
DERIVED_LIMB_LEADS = ('III', 'aVR', 'aVL', 'aVF')


@dataclass
class Waveform:
    """One multiplex group: label, originality and per-lead int16 samples."""
    label: str                              # 'Rhythm' or 'Median'
    originality: str                        # 'ORIGINAL' or 'DERIVED'
    sampling_frequency: float               # Hz
    units_per_bit: float                    # microvolts per least significant bit
    leads: Dict[str, np.ndarray] = field(default_factory=dict)
    derived: Set[str] = field(default_factory=set)   # leads computed by derive_leads()
    highpass_hz: Optional[float] = None     # lower edge of the pass band -> (003A,0220)
    lowpass_hz: Optional[float] = None      # upper edge of the pass band -> (003A,0221)
    notch_hz: Optional[float] = None        # mains notch -> (003A,0222)
    sample_skew: str = '0'                  # (003A,0215)


@dataclass
class Measurements:
    """Global measurements of the record, in fixed units.

    ``fiducials`` holds 0-based sample positions in the median group for the
    keys ``p_onset``, ``p_offset``, ``qrs_onset``, ``qrs_offset`` and
    ``t_offset``, at ``fiducial_sampling_frequency`` hertz. The writer rescales
    them to the median group's own sampling frequency if the two differ.
    """
    ventricular_rate: Optional[float] = None    # /min
    atrial_rate: Optional[float] = None         # /min
    pr_ms: Optional[float] = None
    qrs_ms: Optional[float] = None
    qt_ms: Optional[float] = None
    qtc_ms: Optional[float] = None
    p_axis_deg: Optional[float] = None
    qrs_axis_deg: Optional[float] = None
    t_axis_deg: Optional[float] = None
    fiducials: Dict[str, int] = field(default_factory=dict)
    fiducial_sampling_frequency: Optional[float] = None

    def any(self) -> bool:
        return any(v is not None for v in (
            self.ventricular_rate, self.atrial_rate, self.pr_ms, self.qrs_ms,
            self.qt_ms, self.qtc_ms, self.p_axis_deg, self.qrs_axis_deg,
            self.t_axis_deg)) or bool(self.fiducials)


@dataclass
class EcgRecord:
    source_format: str
    waveforms: List[Waveform] = field(default_factory=list)

    # Patient
    patient_id: Optional[str] = None
    patient_name: Optional[str] = None      # DICOM PN form, family^given
    sex: Optional[str] = None               # 'M', 'F' or None (unknown)
    age_value: Optional[int] = None
    age_unit: str = 'Y'                     # 'Y', 'M', 'W' or 'D'
    birth_date: Optional[str] = None        # YYYYMMDD
    ethnic_group: Optional[str] = None

    # Timing (YYYYMMDD / HHMMSS)
    acquisition_date: Optional[str] = None
    acquisition_time: Optional[str] = None
    content_date: Optional[str] = None      # falls back to the acquisition instant
    content_time: Optional[str] = None

    # Equipment and site
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    software_version: Optional[str] = None
    institution: Optional[str] = None
    department: Optional[str] = None
    station: Optional[str] = None
    operator: Optional[str] = None
    referring_physician: Optional[str] = None
    study_description: Optional[str] = None

    measurements: Measurements = field(default_factory=Measurements)
    diagnosis: List[str] = field(default_factory=list)
    # The source's own measurement elements, untouched. Kept so that coverage
    # reports can say what a format carries even where no mapping exists yet.
    raw_measurements: Dict[str, str] = field(default_factory=dict)

    def median_group_index(self) -> Optional[int]:
        """1-based index of the median (representative beat) group, if any."""
        for i, w in enumerate(self.waveforms, start=1):
            if w.label.lower() == 'median' or w.originality == 'DERIVED':
                return i
        return None


def derive_leads(leads: Dict[str, np.ndarray]) -> Tuple[Dict[str, np.ndarray], Set[str]]:
    """Return the leads in standard order with the four limb leads filled in.

    GE MUSE, and several other formats, store the eight independent leads and
    leave III, aVR, aVL and aVF to be computed from I and II by the standard
    relations. Leads the source already carries are kept as they are. The
    second return value names the leads this function computed, so that the
    writer can mark them with Channel Derivation Description (003A,020C).
    """
    out = dict(leads)
    derived: Set[str] = set()
    if 'I' in out and 'II' in out:
        i = out['I'].astype(np.int32)
        ii = out['II'].astype(np.int32)
        n = min(len(i), len(ii))
        i, ii = i[:n], ii[:n]
        candidates = {
            'III': ii - i,
            'aVR': -(i + ii) // 2,
            'aVL': i - ii // 2,
            'aVF': ii - i // 2,
        }
        for name, arr in candidates.items():
            if name not in out:
                out[name] = np.clip(arr, -32768, 32767).astype(np.int16)
                derived.add(name)
    ordered = {k: out[k] for k in LEAD_ORDER if k in out}
    # keep any non-standard leads the source carried, after the standard twelve
    for k, v in out.items():
        if k not in ordered:
            ordered[k] = v
    return ordered, derived

"""Per-patient surrogate identifiers and date offsets for one conversion run.

PS3.15 Section E.1.1 asks a de-identifier to keep the replacement values of the
Patient entity consistent across the instances it protects, so a run assigns one
surrogate Patient ID per source patient. When dates are shifted rather than
aggregated (Retain Longitudinal Temporal Information with Modified Dates
Option, ``--date-shift``), the run also draws one whole-day offset per patient,
so that the intervals between a patient's records survive de-identification and
an imaging de-identifier can apply the same offset to that patient's studies.

The table that links surrogates and offsets to the source identifiers
(``mrn_mapping_table.json``, written next to the output) is identifying: it
exists so that a study can re-link records under its own governance and must
never leave the institution together with the objects.
"""
import random
from typing import Dict, Optional, Tuple

SHIFT_RANGE_DAYS = (-3650, -365)     # one to ten years into the past, drawn once per patient


class SurrogateTable:
    def __init__(self, date_shift: bool = False, rng: Optional[random.Random] = None):
        self.date_shift = date_shift
        self._rng = rng or random.SystemRandom()
        self._by_source: Dict[str, Tuple[str, Optional[int]]] = {}
        self.rows: Dict[str, dict] = {}

    def lookup(self, source_id: Optional[str], fallback_key: str) -> Tuple[str, Optional[int]]:
        """Surrogate and offset for a source patient; a record without a patient
        identifier is keyed by ``fallback_key`` so that unrelated records never share one."""
        key = source_id if source_id else fallback_key
        hit = self._by_source.get(key)
        if hit is None:
            surrogate = f'{len(self._by_source) + 1:06d}'
            offset = self._rng.randint(*SHIFT_RANGE_DAYS) if self.date_shift else None
            hit = self._by_source[key] = (surrogate, offset)
        return hit

    def record(self, input_name: str, output_name: str, source_id: Optional[str],
               surrogate: str, offset: Optional[int]) -> None:
        row = {'mrn': surrogate, 'original_mrn': source_id or ''}
        if self.date_shift:
            row['date_offset_days'] = offset
        row['ecg_dicom_file'] = output_name
        self.rows[input_name] = row

    def __len__(self) -> int:
        return len(self._by_source)

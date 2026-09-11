# Changelog

All notable changes to ecg2dcm. Dates are ISO 8601.

## 1.3.1 - 2026-09-12

Documentation and code-meaning alignment with PS3.16; no change to any code value, attribute,
or conversion outcome. Objects written by 1.3.0 and 1.3.1 differ only in the two strings below.

### Changed
- Code meaning of the patient state (SCT 128975004) is "Resting state", as printed in CID 3262.
- Code meaning of the rate unit ({H.B.}/min, UCUM) is "BPM", as in the UNITS constraint of TID 3713.
- `docs/mapping/coded_values.csv` and `codes.CODED_VALUES` name the governing groups with their current PS3.16 titles
  (CID 3262 ECG Patient State Value, CID 3263 Electrode Placement Value) and TID 3713 alone for the interval and QTc rows.
- Example DICOM files regenerated with 1.3.1.

## 1.3.0 - 2026-09-11

Corrections found during peer review of CMPB-D-25-07854, and the multi-format
front ends used for its external evaluation.

### Changed
- **SOP Class is now General ECG Waveform Storage** (1.2.840.10008.5.1.4.1.1.9.1.2).
  The 12-Lead ECG IOD limits the total number of channels across all multiplex
  groups to 13 (PS3.3 A.34.3.4.4); a rhythm group and a median group of twelve
  channels each carry 24. The module table is identical, so the attribute
  mapping is unchanged.
- **One pipeline.** Every format, GE MUSE included, is parsed into a
  vendor-neutral record (`ecg2dcm/ir.py`) and written by a single writer
  (`ecg2dcm/writer.py`). The former `XMLFile`/`ecg_dcm_metadata` code path is gone.
- **Waveform Annotation redesigned.** P, QRS and T axes are coded from CID 3229
  (MDC 2:16128, 2:16132, 2:16136) instead of LOINC. The fiducial points
  (POnset, POffset, QOnset, QOffset, TOffset) are no longer written as numeric
  values in milliseconds: in GE MUSE they are sample positions of the median
  beat, so they now become Referenced Sample Positions of SEGMENT annotations
  for the PR, QRS and QT intervals and for the P wave (CID 3335). Rates
  reference the rhythm group; intervals, QTc and axes reference the median
  group. Rate units are `{H.B.}/min` as in TID 3713.
- **Patient's Sex** is left empty (Type 2) when the source has no gender or an
  unrecognised value; 1.2.0 wrote `O` for absent and `F` for anything that was
  not `male`.
- Study ID is 16 random digits; Instance Number and Series Number are the
  object's index within the run.

### Added
- Front ends for GE CardioSoft, Philips Sierra (via `sierraecg`), HL7 aECG,
  Mortara ELI Link, Schiller SEMA and WFDB, with format detection
  (`ecg2dcm-convert`).
- Channel Derivation Description (003A,020C) on the four derived limb leads in
  both groups.
- `ecg2dcm.conformance.check_iod_constraints()`, the General ECG IOD content
  constraints that attribute-level validators do not evaluate.
- `--uid-root` on both commands; `--keep-identity` to disable de-identification.
- Ethnic Group (0010,2160) from `<Race>`, Patient's Age with the source's units,
  Operators' Name, and the interpretation text (with `--keep-identity` only).
- `docs/` (attribute mapping, coded values, de-identification, conformance),
  `examples/` (synthetic and public teaching files with their DICOM output),
  `tests/`, `analysis/` (the scripts behind the paper's tables), and a
  Trusted Publishing workflow for PyPI.

## 1.2.0 - 2026-09-08

First release under the name `ecg2dcm`, on GitHub with an MIT license.
Corrections to 1.1.10 reported in the revision of CMPB-D-25-07854:

- Channel Source Sequence coded from CID 3001 (MDC) instead of LOINC lead names.
- Filter Low/High Frequency assigned to the correct pass-band edges, with
  `<HighPassFilter>` converted from hundredths of a hertz; Notch Filter
  Frequency written from `<ACFilter>`.
- Multiplex Group Label written; the median group carries twelve channels.
- Measurement unit code value and meaning no longer swapped; LOINC designator `LN`.
- Records whose acquisition date cannot be parsed are refused with a stated
  reason instead of receiving an invalid Type 1 value.
- UID root changed from GE HealthCare's OID to a neutral placeholder.

## 1.1.10 - 2025-07-11

Last release under the name `XML2DCM-ECG` (PyPI), GE MUSE only.

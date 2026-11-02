# Changelog

All notable changes to ecg2dcm. Dates are ISO 8601.

## 1.3.2 - 2026-11-03

De-identification stated and recorded in terms of DICOM PS3.15. The set of 32
unconditionally required attributes counted in the manuscript is unchanged,
but Patient ID and date/time values can differ under the revised handling.
The original study results were obtained with v1.3.0; the five public WFDB
datasets were revalidated with v1.3.2 using the default date rule. Existing
code values are unchanged.

### Changed
- The rule set is now documented as the Basic Application Level Confidentiality
  Profile of PS3.15 with the Clean Structured Content, Clean Descriptors, Retain
  Longitudinal Temporal Information with Modified Dates and Retain Patient
  Characteristics Options (`docs/deidentification.md` gives the Table E.1-1 action
  for every attribute).
- The four Type 3 identity attributes, Institution Name, Institutional Department
  Name, Station Name and Operators' Name, are removed instead of being overwritten
  with `Anonymized`, following their Table E.1-1 actions.
- Every de-identified object carries Patient Identity Removed (0012,0062) = YES,
  De-identification Method (0012,0063), De-identification Method Code Sequence
  (0012,0064) with the five CID 7050 codes, and Longitudinal Temporal Information
  Modified (0028,0303) = MODIFIED; `codes.CODED_VALUES` and
  `docs/mapping/coded_values.csv` list the five codes.
- Study Description is the fixed string `12-Lead ECG` in every de-identified object,
  whatever the adapter or caller supplied.
- Both commands assign one surrogate Patient ID per source patient and write the
  surrogate table (`ecg2dcm.surrogates`); `ecg2dcm-convert` previously numbered
  surrogates per file and wrote no table.

### Added
- `--date-shift` (both commands) and `build(..., date_shift_days=)`: dates and times
  of a patient are shifted together by one whole-day offset drawn once per patient
  (one to ten years into the past) instead of being aggregated to the month, so
  that the intervals between a patient's records survive; the offset is kept in
  the surrogate table.

### Fixed
- Existing output directories are refused before conversion; `--start-index`
  sets the first patient surrogate as well as the first Instance Number.
- Unknown Multiplex Group Labels are omitted during de-identification.
- Mapping rows use unique input path keys, repeated paths are processed once,
  and colliding output file names receive numeric suffixes instead of being
  overwritten. Rows are recorded after the object is saved.
- WFDB front end: the age comment was stored in a field the writer never read, so
  Patient's Age was not written for WFDB records; it is now.
- WFDB front end: a `subject_id` (or `patient_id`) header comment, as MIMIC-IV-ECG
  carries, is used as the patient identifier instead of the record name.
- Example DICOM files regenerated with 1.3.2.

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

Corrections found during peer review of the accompanying manuscript, and the
multi-format front ends used for its external evaluation.

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
Corrections to 1.1.10 reported in the revision of the accompanying manuscript:

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

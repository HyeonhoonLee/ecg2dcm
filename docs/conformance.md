# Conformance: what is checked, and by what

## Which IOD

Objects are written as **General ECG Waveform Storage**
(SOP Class `1.2.840.10008.5.1.4.1.1.9.1.2`), not 12-Lead ECG Waveform Storage.

The two IODs have identical module tables (PS3.3 Table A.34.3-1 and
Table A.34.4-1), so the attribute mapping is the same. They differ in their
content constraints:

| Constraint | 12-Lead ECG IOD (A.34.3.4) | General ECG IOD (A.34.4.4) |
|---|---|---|
| Waveform Sequence items | 1 to 5 | 1 to 4 |
| Channels per item | 1 to 13 | 1 to 24 |
| Channels across all items | **at most 13** | no limit |
| Samples per item | at most 16,384 | no limit |
| Sampling Frequency | 200 to 1000 Hz | 200 to 1000 Hz |
| Channel Source Sequence | Baseline CID 3001 | **Defined** CID 3001 |
| Waveform Sample Interpretation | SS | SS |

A record with a twelve-channel rhythm group and a twelve-channel median group
carries 24 channels, which the 12-Lead ECG IOD does not permit. Earlier versions
of this package (1.1.10, 1.2.0) wrote such objects under the 12-Lead ECG SOP
Class; they passed attribute-level validation because that validation does not
evaluate content constraints.

## Two levels of checking

1. **Attribute-level validation** (dicom-validator, DVTk): module presence,
   attribute presence and type, value representation, conditional requirements.
   Run it with `pip install "ecg2dcm[validate]"` and the `validate_iods`
   command of dicom-validator, or through `analysis/stratified_conversion.py`.
2. **IOD content constraints** (PS3.3 A.34.4.4): `ecg2dcm.conformance.check_iod_constraints(ds)`
   returns the list of violated constraints, empty for a conformant object. It
   also checks that every Waveform Annotation references an existing multiplex
   group and channel and that temporal ranges fall inside the referenced group.

Neither level verifies that a coded value belongs to the context group named
for it. `docs/mapping/coded_values.csv` lists every code the writer emits with
its governing context group or template, and the package tests assert that the
table matches the code.

## Waveform Annotation concept names

Neither ECG IOD designates a context group for the Concept Name Code Sequence
of the Waveform Annotation Module (PS3.3 C.10.10 leaves it to the IOD, and
A.34.3.4 / A.34.4.4 do not set one). The concept names used here are taken
from TID 3713 "ECG Global Measurements" (rates and intervals), CID 3229 "ECG
Axis Measurement" (axes) and CID 3335 "ECG Annotation" (the P wave).

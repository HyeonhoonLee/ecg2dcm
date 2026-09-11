# De-identification

Every object is de-identified unless `--keep-identity` is passed. The rules are
implemented once, in `ecg2dcm.writer.deidentify()`, and apply to every source
format.

| Attribute | Data type | Rule | Example (source → output) |
|---|---|---|---|
| Patient ID (0010,0020) | identifier | replaced by a six-digit surrogate; one surrogate per source patient within a run | `123456789` → `000001` |
| Patient's Name (0010,0010) | person name | literal `Anonymized` | `Hong^Kil Dong` → `Anonymized` |
| Patient's Birth Date (0010,0030) | date | empty (Type 2) | `19800101` → `` |
| Referring Physician's Name (0008,0090) | person name | literal `Anonymized` | |
| Operators' Name (0008,1070) | person name | literal `Anonymized` | |
| Institution Name (0008,0080) | location | literal `Anonymized` | `SEOUL NATIONAL UNIVERSITY HOSP.` → `Anonymized` |
| Institutional Department Name (0008,1040) | location | literal `Anonymized` | `OUTPATIENT EKG ROOM` → `Anonymized` |
| Station Name (0008,1010) | location | literal `Anonymized` | `IMC` → `Anonymized` |
| Acquisition DateTime (0008,002A) | date/time | day set to 01, time to 000000 | `20190817091511` → `20190801000000` |
| Study Date / Time (0008,0020 / 0030) | date/time | day set to 01, time to 000000 | `20190817` / `091511` → `20190801` / `000000` |
| Content Date / Time (0008,0023 / 0033) | date/time | day set to 01, time to 000000 | `20190817` / `093421` → `20190801` / `000000` |
| Unformatted Text Value (0070,0006) | free text | not written (vendor interpretation text can embed reader names) | |

Attributes that carry no identity are kept as they are: sex, age, ethnic group,
device model, software versions, filter settings, the waveforms and the
measurements. Year and month of acquisition are kept so that within-patient
ordering and coarse follow-up intervals survive; the day and the time do not.

The surrogate table of a batch run (`mrn_mapping_table.json`, written by the
`ecg2dcm` command next to the output) links surrogates to source patient IDs.
It exists so that a study can re-link records under its own governance; it is
identifying and must be stored accordingly, never alongside the DICOM objects
that leave the institution.

UIDs are generated afresh under the configured root (`--uid-root`) and carry
no source information.

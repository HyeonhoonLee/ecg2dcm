# De-identification

Every object is de-identified unless `--keep-identity` is passed. The rules are
implemented once, in `ecg2dcm.writer.deidentify()` and `ecg2dcm.writer.build()`,
and apply to every source format.

The rule set implements the **Basic Application Level Confidentiality Profile**
of DICOM PS3.15 (Annex E, Table E.1-1) for the attributes of the General ECG
IOD, with four of its options:

- **Retain Longitudinal Temporal Information with Modified Dates Option** (113107):
  by default dates are aggregated to the first day of the month and times are
  set to `000000` (the form of aggregation that PS3.15 E.3.6 describes); with
  `--date-shift` the date and time of every record of a patient are shifted
  together by one constant whole-day offset instead, so that the intervals
  between that patient's records survive.
- **Retain Patient Characteristics Option** (113108): sex, age and ethnic group are kept.
- **Clean Structured Content Option** (113104): the Acquisition Context Sequence and
  the Waveform Annotation Sequence are kept with their coded items only.
- **Clean Descriptors Option** (113105): Study Description, Multiplex Group Label
  and Channel Derivation Description are written from a fixed vocabulary.
  Multiplex Group Label is retained only as `Rhythm` or `Median`; unknown labels
  are omitted. The free-text diagnosis statement is not written.

Every de-identified object records this in Patient Identity Removed (0012,0062)
= `YES`, De-identification Method (0012,0063) (release and date rule),
De-identification Method Code Sequence (0012,0064) (the five CID 7050 codes
113100, 113104, 113105, 113107, 113108) and Longitudinal Temporal Information
Modified (0028,0303) = `MODIFIED`.

| Attribute | Type | Table E.1-1 (Basic Profile) | Option | Rule | Example (source → output) |
|---|---|---|---|---|---|
| Patient ID (0010,0020) | 2 | Z/D | – | six-digit surrogate, one per source patient within a run | `123456789` → `000001` |
| Patient's Name (0010,0010) | 2 | Z | – | literal `Anonymized` | `Hong^Kil Dong` → `Anonymized` |
| Patient's Birth Date (0010,0030) | 2 | Z | – | empty | `19800101` → `` |
| Patient's Sex (0010,0040) | 2 | Z | Retain Patient Characteristics (K) | kept | |
| Patient's Age (0010,1010) | 3 | X | Retain Patient Characteristics (K) | kept | |
| Ethnic Group (0010,2160) | 3 | X | Retain Patient Characteristics (K) | kept as coded in the source | |
| Referring Physician's Name (0008,0090) | 2 | Z | – | literal `Anonymized` | |
| Accession Number (0008,0050) | 2 | Z | – | empty (in either mode) | |
| Study ID (0020,0010) | 2 | Z | – | generated, 16 digits (in either mode) | |
| Study Description (0008,1030) | 3 | X | Clean Descriptors (C) | fixed string `12-Lead ECG` | |
| Study Date / Time (0008,0020 / 0030) | 2 | Z | Modified Dates (C) | day set to 01 and time to 000000; or shifted together by the patient's offset | `20190817` / `091511` → `20190801` / `000000` |
| Content Date / Time (0008,0023 / 0033) | 1 | Z/D | Modified Dates (C) | as Study Date / Time | `20190817` / `093421` → `20190801` / `000000` |
| Acquisition DateTime (0008,002A) | 1 | X/Z/D | Modified Dates (C) | date and time rules combined | `20190817091511` → `20190801000000` |
| Operators' Name (0008,1070) | 3 | X/Z/D | – | removed | |
| Institution Name (0008,0080) | 3 | X/Z/D | – (Retain Institution Identity not applied) | removed | `SEOUL NATIONAL UNIVERSITY HOSP.` → (removed) |
| Institutional Department Name (0008,1040) | 3 | X | – (Retain Institution Identity not applied) | removed | |
| Station Name (0008,1010) | 3 | X/Z/D | – (Retain Device Identity not applied) | removed | |
| Study, Series, SOP Instance UID | 1 | U | – (Retain UIDs not applied) | generated under `--uid-root` (in either mode) | |
| Acquisition Context Sequence (0040,0555) | 2 | X/Z | Clean Structured Content (C) | kept: coded lead system and patient state only | |
| Waveform Annotation Sequence (0040,B020) | 1 (conditional module) | X/D | Clean Structured Content (C) | kept with the coded measurement items; the free-text item (Unformatted Text Value (0070,0006): D, Clean Descriptors C) is not written | `NORMAL SINUS RHYTHM` → (not written) |
| Multiplex Group Label (003A,0020) | 3 | X | Clean Descriptors (C) | fixed vocabulary (`Rhythm`, `Median`); unknown labels omitted | |
| Channel Derivation Description (003A,020C) | 3 | X | Clean Descriptors (C) | fixed string naming the source leads | |

Attributes of the IOD that Table E.1-1 does not list (Manufacturer, Manufacturer's
Model Name, Software Versions, Series Number, Instance Number, the channel
definition and measurement attributes) are written unchanged; no private
attribute is written, and the File Meta Information is created afresh. With
`--date-shift`, the offset is a whole number of days drawn once per patient
between one and ten years into the past.

The surrogate table of a run (`mrn_mapping_table.json`, written by both commands
next to the output) links surrogates, and with `--date-shift` the offsets, to the
source patient identifiers. It exists so that a study can re-link records under
its own governance and so that an imaging de-identifier can apply the same offset
to the patient's imaging studies; it is identifying and must be stored accordingly,
never alongside the DICOM objects that leave the institution.

UIDs are generated afresh under the configured root (`--uid-root`) and carry
no source information. The de-identification profile does not by itself
guarantee that an object carries no identifying information (PS3.15 Annex E); it
is one part of a governed de-identification process.


Each command requires a new or empty output directory and refuses an occupied
or concurrently used directory before conversion begins. All records intended
to share patient surrogates and date offsets must be converted together in one
run. An existing mapping table is not loaded for a later run. For
`ecg2dcm-convert`, `--start-index` sets both the first Instance Number and the
first allocated patient surrogate; repeated records of a patient reuse that
patient's surrogate and date offset within the run.

The MUSE command keys mapping rows by the input path relative to the input
root and records the output path relative to the output root. The multi-format
command uses resolved input paths as keys, processes a repeated input path
once, and adds numeric suffixes to colliding output file names. A mapping row
is recorded only after the object has been saved.

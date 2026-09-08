# ECG2DCM

Convert GE MUSE XML electrocardiogram files to DICOM 12-Lead ECG Waveform Storage.

This is the implementation reported in *ECG2DCM: An open-source framework for converting
GE MUSE XML electrocardiogram data to DICOM* (Computer Methods and Programs in Biomedicine,
manuscript CMPB-D-25-07854). Release **v1.2.0** corresponds to the results in that paper.

```
pip install ecg2dcm
ecg2dcm --help
```

Requires Python 3.10 or later. Licensed under the MIT License.

Derived from the earlier `ecg2dcm` package (v1.1.10). Version 1.2.0 corrects the DICOM
coding of lead identifiers, filter settings and measurement units, writes the multiplex group
label, derives the limb leads for both waveform groups, and refuses records whose acquisition
instant cannot be recovered rather than writing an invalid Type 1 value. See the release notes.

**Before production use, replace the UID root.** `ecg2dcm/ecg_dcm_metadata.py` issues Study,
Series and SOP Instance UIDs under a neutral placeholder root; it must be your organisation's
own registered OID.

---

# ecg2dcm

## Description

This repository contains a Python-based solution for converting ECG data from XML format to the DICOM (Digital Imaging
and Communications in Medicine) format. The goal of this project is to facilitate the process of transforming clinical
ECG data stored in XML files into a standardized, widely-used DICOM format, which is essential for healthcare systems,
medical imaging devices, and Electronic Health Record (EHR) systems.

The solution handles the extraction and conversion of ECG information, including patient details, acquisition context,
and waveform data, from XML files into the DICOM format. The project also integrates essential metadata such as the type
of ECG lead (e.g., Lead I, Lead II), device information (e.g., acquisition device, software versions), and patient
demographics.

## Installation

1. Clone this repository to your local machine using the following command:
   ```
   bash
   
   git clone https://github.com/HyeonhoonLee/ecg2dcm.git
   ```

2. Install the required Python packages using the following command:
   ```
    bash
   
    pip install -r requirements.txt
    ```

## Usage

1. Place your ECG XML files in a directory (e.g., `data/cdm`) under your project root. Ensure each file follows a consistent naming format if you plan to extract metadata from filenames.
2. Run the following command to convert the XML files to DICOM format:

   ```
   bash
   
    python main.py --debug=True \ 
   --debug_n=5 \
   --project_root=/path/to/project \
   --data_root=/path/to/project \
   --ecg_xml_dir=/path/to/data \
   --output_dir=/path/to/output \
   --filename_pattern="MUSE_(?P<examination_date>\d{8})_(?P<examination_time>\d{6})_(?P<seq>\d{5})" \
   --out_filename_pattern="ECG_DICOM_{examination_date}_{seq}"

   ```

## Command Line Arguments

| Argument                  | Type    | Required | Default     | Description                                                              |
|--------------------------|---------|----------|-------------|--------------------------------------------------------------------------|
| `--debug`                | `bool`  | No       | `False`     | Enable debug mode to process a limited number of files                   |
| `--debug_n`              | `int`   | No       | `5`         | Number of files to process when debug is enabled                         |
| `--project_root`         | `str`   | Yes      | —           | Root directory of the project                                            |
| `--data_root`            | `str`   | Yes      | —           | Root path for input data                                                 |
| `--ecg_xml_dir`          | `str`   | Yes      | —           | Relative path to the directory containing ECG XML files                  |
| `--output_dir`           | `str`   | No       | `ecg_dcm`   | Directory (under project_root) where converted DICOM files will be saved | 
| `--filename_pattern`     | `str`   | Yes      | —           | Regex pattern to extract metadata from filenames                         |
| `--out_filename_pattern` | `str`   | Yes      | —           | Format for naming output DICOM files using named groups from the regex   |


### Pattern Requirements

To ensure consistent anonymization and file management, the following pattern requirements must be satisfied.

1. **Filename Pattern (`--filename_pattern`)**
   - Must include a named group that extracts a **date value** from the XML filename.  
     Example: `(?P<examination_date>\d{8})`
   - The ECG XML files must have filenames that contain this date value, so the pattern can correctly extract it.

2. **Output Filename Pattern (`--out_filename_pattern`)**
   - Must contain:
     - Exactly **one date-related key** (e.g., `{examination_date}`)
     - A **sequence number key** (e.g., `{seq}`) to differentiate multiple files with the same date

This is crucial for maintaining uniqueness among converted DICOM files, especially when multiple ECGs share the same date.

If `seq` is not included in the `--out_filename_pattern`, a warning will be printed and `_{seq}` will be **automatically appended** to ensure file uniqueness:

```text
Warning: No sequence number in output filename pattern. Sequence numbers will not be used to differentiate files with the same date.
Add "seq" to the output filename pattern to enable sequence differentiation.
```

If more than one `{...date...}` key is found in the output filename pattern, the script will raise an error to enforce a single date field:

```text
AssertionError: Expected one date key in the output filename pattern, found 2.
```

Make sure that:
- Your `--filename_pattern` includes the group(s) matching the required keys (e.g., `(?P<examination_date>...)`)
- Your ECG XML filenames include a date string that matches this pattern
- Your `--out_filename_pattern` uses the same group names as placeholders (e.g., `{examination_date}`, `{seq}`)


### Example

- **Input filename**: `MUSE_20250711_153012_00001.xml`
- **Extracted**:
  - `examination_date = 20250711`
- **Output filename**: `ECG_DICOM_20250711_00001.dcm`


## Example results

The following are examples of the ECG data converted from XML to DICOM format:
![ecg_dicom.png](assets%2Fecg_dicom.png)
   

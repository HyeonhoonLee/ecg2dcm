"""Package tests: the two example files must convert to conformant objects
whose annotations point where the source says they should."""
import csv
import os
import xml.etree.ElementTree as ET

import pydicom
import pytest

from ecg2dcm import __version__, build, check_iod_constraints, codes, parse, sniff
from ecg2dcm.surrogates import SurrogateTable
from ecg2dcm.adapters import wfdb
import numpy as np
from ecg2dcm.adapters import muse
from ecg2dcm.writer import _ds

HERE = os.path.dirname(os.path.abspath(__file__))
EX = os.path.join(HERE, '..', 'examples')
SYNTH = os.path.join(EX, 'synthetic_muse.xml')
TEACH = os.path.join(EX, 'guangxi_teaching_sinus_rhythm.xml')


@pytest.mark.parametrize('path', [SYNTH, TEACH])
def test_muse_example_converts_and_conforms(path):
    name, _ = sniff(path)
    assert name == 'GE MUSE'
    ds = build(parse(path), index=7)
    assert ds.SOPClassUID == codes.SOP_GENERAL_ECG
    assert ds.Modality == 'ECG'
    assert len(ds.WaveformSequence) == 2
    labels = [g.MultiplexGroupLabel for g in ds.WaveformSequence]
    assert labels == ['Rhythm', 'Median']
    assert [g.WaveformOriginality for g in ds.WaveformSequence] == ['ORIGINAL', 'DERIVED']
    assert all(int(g.NumberOfWaveformChannels) == 12 for g in ds.WaveformSequence)
    assert check_iod_constraints(ds) == []
    # derived limb leads are marked in both groups
    for g in ds.WaveformSequence:
        derived = [c.ChannelSourceSequence[0].CodeValue for c in g.ChannelDefinitionSequence
                   if c.get('ChannelDerivationDescription')]
        assert derived == ['2:61', '2:62', '2:63', '2:64']
    # de-identification
    assert str(ds.PatientName) == 'Anonymized'
    assert ds.PatientID == '000007'
    assert ds.PatientBirthDate == ''
    assert ds.StudyDate.endswith('01') and ds.StudyTime == '000000'
    assert ds.AcquisitionDateTime.endswith('01000000')
    for tag in ('InstitutionName', 'InstitutionalDepartmentName', 'StationName', 'OperatorsName'):
        assert tag not in ds                       # Type 3 identity attributes are removed (PS3.15 Table E.1-1: X)
    assert str(ds.ReferringPhysicianName) == 'Anonymized'
    assert ds.StudyDescription == '12-Lead ECG'
    assert not any(a.get('UnformattedTextValue') for a in ds.WaveformAnnotationSequence)
    # the object records the profile and options (PS3.15 E.1.1 item 6, E.3.6)
    assert ds.PatientIdentityRemoved == 'YES'
    assert ds.LongitudinalTemporalInformationModified == 'MODIFIED'
    assert ds.DeidentificationMethod == f'ecg2dcm {__version__}: dates aggregated to month'
    assert [c.CodeValue for c in ds.DeidentificationMethodCodeSequence] == ['113100', '113104', '113105', '113107', '113108']
    assert all(c.CodingSchemeDesignator == 'DCM' for c in ds.DeidentificationMethodCodeSequence)


def test_fiducials_become_sample_positions_of_the_median_group():
    root = ET.parse(SYNTH).getroot()
    m = root.find('RestingECGMeasurements')
    g = lambda t: int(m.findtext(t))
    ds = build(parse(SYNTH))
    by_code = {a.ConceptNameCodeSequence[0].CodeValue: a for a in ds.WaveformAnnotationSequence}
    pr, qrs, qt, p = by_code['2:15872'], by_code['2:16156'], by_code['2:16160'], by_code['10:256']
    assert list(pr.ReferencedSamplePositions) == [g('POnset') + 1, g('QOnset') + 1]
    assert list(qrs.ReferencedSamplePositions) == [g('QOnset') + 1, g('QOffset') + 1]
    assert list(qt.ReferencedSamplePositions) == [g('QOnset') + 1, g('TOffset') + 1]
    assert list(p.ReferencedSamplePositions) == [g('POnset') + 1, g('POffset') + 1]
    assert all(list(a.ReferencedWaveformChannels) == [2, 0] for a in (pr, qrs, qt, p))
    assert all(a.TemporalRangeType == 'SEGMENT' for a in (pr, qrs, qt, p))
    # the interval in milliseconds agrees with the segment length at 500 Hz
    assert float(pr.NumericValue) == (g('QOnset') - g('POnset')) * 2
    assert pr.MeasurementUnitsCodeSequence[0].CodeValue == 'ms'
    assert list(by_code['2:16016'].ReferencedWaveformChannels) == [1, 0]
    assert by_code['2:16016'].MeasurementUnitsCodeSequence[0].CodeValue == '{H.B.}/min'
    assert by_code['2:16128'].ConceptNameCodeSequence[0].CodingSchemeDesignator == 'MDC'


def test_keep_identity_writes_source_values():
    ds = build(parse(SYNTH), deidentify_record=False)
    assert 'PatientIdentityRemoved' not in ds and 'DeidentificationMethodCodeSequence' not in ds
    assert 'LongitudinalTemporalInformationModified' not in ds
    assert str(ds.PatientName) == 'Synthetic^Example'
    assert ds.PatientID == 'SYNTH0001'
    assert ds.StudyDate == '20250817' and ds.StudyTime == '091511'
    assert ds.InstitutionName == 'EXAMPLE HOSPITAL'
    assert ds.EthnicGroup == 'UNKNOWN'
    assert ds.PatientAge == '045Y'
    texts = [a.UnformattedTextValue for a in ds.WaveformAnnotationSequence if a.get('UnformattedTextValue')]
    assert texts == ['Sinus rhythm (synthetic example)']


def test_uid_root_is_honoured():
    ds = build(parse(SYNTH), uid_root='1.2.826.0.1.3680043.10.999')
    root = '1.2.826.0.1.3680043.10.999.'
    assert ds.StudyInstanceUID.startswith(root)
    assert ds.SeriesInstanceUID.startswith(root) and ds.SOPInstanceUID.startswith(root)
    assert ds.file_meta.MediaStorageSOPInstanceUID == ds.SOPInstanceUID


def test_missing_gender_is_left_empty_not_other():
    rec = parse(SYNTH)
    rec.sex = None
    ds = build(rec)
    assert ds.PatientSex == ''


def test_record_without_acquisition_date_is_refused():
    rec = parse(SYNTH)
    rec.acquisition_date = None
    with pytest.raises(ValueError, match='acquisition date'):
        build(rec)


def test_ds_never_exceeds_16_bytes():
    for v in (4.88, 1000 / 2317, 1e-7, 123456789012345678.0, 0.1 + 0.2, 500, 0.43159257660768235):
        assert len(_ds(v)) <= 16, v
    assert _ds(500) == '500' and _ds(4.88) == '4.88'


def test_coded_values_table_matches_code():
    path = os.path.join(HERE, '..', 'docs', 'mapping', 'coded_values.csv')
    with open(path, newline='', encoding='utf-8') as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == len(codes.CODED_VALUES)
    for row, (attr, code, unit, gov, src) in zip(rows, codes.CODED_VALUES):
        assert (row['Attribute'], row['Code Value'], row['Coding Scheme Designator'], row['Code Meaning']) == (attr, code.value, code.scheme, code.meaning)


def test_all_lead_codes_are_cid_3001_members():
    for code in codes.CID_3001_ECG_LEAD.values():
        assert code.value in codes.CID_3001_CODE_VALUES


def test_written_file_reads_back():
    ds = build(parse(TEACH))
    out = os.path.join(HERE, '_tmp_teach.dcm')
    try:
        ds.save_as(out, write_like_original=False)
        back = pydicom.dcmread(out)
        assert back.file_meta.MediaStorageSOPClassUID == codes.SOP_GENERAL_ECG
        assert len(back.WaveformSequence[0].WaveformData) == 12 * 5000 * 2
    finally:
        if os.path.exists(out):
            os.remove(out)


def test_date_shift_preserves_intervals_and_time_of_day():
    rec = parse(SYNTH)                                   # 2025-08-17 09:15:11
    ds = build(rec, date_shift_days=-400)
    assert ds.StudyDate == '20240713' and ds.StudyTime == '091511'
    assert ds.AcquisitionDateTime == '20240713091511'
    assert ds.DeidentificationMethod == f'ecg2dcm {__version__}: dates shifted per patient'
    later = parse(SYNTH)
    later.acquisition_date = '20250820'                  # three days later, same patient, same offset
    ds2 = build(later, date_shift_days=-400)
    from datetime import datetime
    delta = datetime.strptime(ds2.StudyDate, '%Y%m%d') - datetime.strptime(ds.StudyDate, '%Y%m%d')
    assert delta.days == 3


def test_surrogate_table_is_per_patient():
    t = SurrogateTable(date_shift=True)
    s1, o1 = t.lookup('P1', 'file:1')
    s2, o2 = t.lookup('P2', 'file:2')
    s1b, o1b = t.lookup('P1', 'file:3')
    assert (s1, o1) == (s1b, o1b) and s1 != s2
    assert -3650 <= o1 <= -365
    a, _ = t.lookup('', 'file:4'); b, _ = t.lookup('', 'file:5')
    assert a != b                                        # records without a patient identifier never share a surrogate
    t.record('in.xml', 'out.dcm', 'P1', s1, o1)
    assert t.rows['in.xml'] == {'mrn': s1, 'original_mrn': 'P1', 'date_offset_days': o1, 'ecg_dicom_file': 'out.dcm'}


def test_wfdb_subject_id_and_age_are_read(tmp_path):
    n = 10
    data = np.zeros((n, 2), dtype='<i2'); data[:, 0] = np.arange(n); data[:, 1] = -np.arange(n)
    (tmp_path / 'rec1.dat').write_bytes(data.tobytes())
    (tmp_path / 'rec1.hea').write_text(
        'rec1 2 500 10 08:44:00 23/07/2180\n'
        'rec1.dat 16 200.0(0)/mV 16 0 0 0 0 I\n'
        'rec1.dat 16 200.0(0)/mV 16 0 0 0 0 II\n'
        '# <subject_id>: 10000032\n# <age>: 51\n# <sex>: F\n')
    rec = wfdb.parse(str(tmp_path / 'rec1.hea'))
    assert rec.patient_id == '10000032' and rec.age_value == 51 and rec.sex == 'F'
    ds = build(rec, deidentify_record=False)
    assert ds.PatientID == '10000032' and ds.PatientAge == '051Y' and ds.PatientSex == 'F'
    ds = build(rec)
    assert ds.PatientAge == '051Y' and ds.PatientID == '000001'

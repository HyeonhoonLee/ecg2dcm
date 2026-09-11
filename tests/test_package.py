"""Package tests: the two example files must convert to conformant objects
whose annotations point where the source says they should."""
import csv
import os
import xml.etree.ElementTree as ET

import pydicom
import pytest

from ecg2dcm import build, check_iod_constraints, codes, parse, sniff
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
    assert ds.InstitutionName == 'Anonymized'
    assert not any(a.get('UnformattedTextValue') for a in ds.WaveformAnnotationSequence)


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

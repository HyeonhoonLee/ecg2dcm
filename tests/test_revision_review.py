"""Regression checks for isolated review candidates: patient identity and descriptors."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET

import pydicom
import pytest

from ecg2dcm import build, check_iod_constraints, parse
from ecg2dcm.convert import main as convert
from ecg2dcm.main import main as muse_batch
from ecg2dcm.surrogates import SurrogateTable
from ecg2dcm.utils import fresh_output_directory

EXAMPLE = Path(__file__).parent.parent / 'examples' / 'synthetic_muse.xml'


def make_xml(path, patient='SYN-A', date='2025-08-17', time='09:15:11', label=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.parse(EXAMPLE)
    tree.find('PatientDemographics/PatientID').text = patient
    date = datetime.strptime(date, '%Y-%m-%d').strftime('%m-%d-%Y')
    for field in ('AcquisitionDate', 'EditDate'):
        tree.find('TestDemographics/' + field).text = date
    for field in ('AcquisitionTime', 'EditTime'):
        tree.find('TestDemographics/' + field).text = time
    if label is not None:
        tree.find('Waveform/WaveformType').text = label
    tree.write(path, encoding='utf-8')
    return path


def arguments(command, inputs, output):
    if command == 'convert':
        return [str(inputs), '-o', str(output)]
    return ['--project_root', str(output.parent), '--output_dir', output.name,
            '--data_root', str(inputs.parent), '--ecg_xml_dir', inputs.name,
            '--filename_pattern', r'ecg(?P<exam_date>\d{8})',
            '--out_filename_pattern', 'ECG_{exam_date}_{seq}']


def run(command, args):
    return (convert if command == 'convert' else muse_batch)(args)


def snapshot(path):
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.rglob('*') if p.is_file()}


@pytest.mark.parametrize('command', ['convert', 'muse'])
@pytest.mark.parametrize('mode', [[], ['--date-shift'], ['--keep-identity']])
def test_second_run_is_refused_before_existing_outputs_change(tmp_path, command, mode):
    inputs, output = tmp_path / 'inputs', tmp_path / 'output'
    make_xml(inputs / 'ecg20250817.xml')
    args = arguments(command, inputs, output) + mode
    run(command, args)
    before = snapshot(output)
    make_xml(inputs / 'ecg20250818.xml', patient='SYN-B', date='2025-08-18')
    with pytest.raises(SystemExit) as exc:
        run(command, args)
    assert exc.value.code == 2
    assert snapshot(output) == before
    assert len(list(output.glob('*.dcm'))) == 1


@pytest.mark.parametrize('command', ['convert', 'muse'])
def test_existing_empty_directory_is_accepted(tmp_path, command):
    inputs, output = tmp_path / 'inputs', tmp_path / 'output'
    output.mkdir()
    make_xml(inputs / 'ecg20250817.xml')
    run(command, arguments(command, inputs, output))
    assert len(list(output.glob('*.dcm'))) == 1
    assert not (output / '.ecg2dcm-run.lock').exists()


@pytest.mark.parametrize('command', ['convert', 'muse'])
def test_unrelated_content_in_output_is_preserved_and_conversion_refused(tmp_path, command):
    inputs, output = tmp_path / 'inputs', tmp_path / 'output'
    make_xml(inputs / 'ecg20250817.xml')
    output.mkdir()
    (output / 'existing.txt').write_text('preserve this file')
    before = snapshot(output)
    with pytest.raises(SystemExit) as exc:
        run(command, arguments(command, inputs, output))
    assert exc.value.code == 2
    assert snapshot(output) == before


def test_concurrent_conversion_cannot_claim_same_empty_directory(tmp_path):
    output = tmp_path / 'output'
    with fresh_output_directory(output):
        assert (output / '.ecg2dcm-run.lock').exists()
        with pytest.raises(FileExistsError):
            with fresh_output_directory(output):
                pytest.fail('second run acquired the output directory')
        assert (output / '.ecg2dcm-run.lock').exists()
    assert not (output / '.ecg2dcm-run.lock').exists()


def test_directory_claim_is_released_on_exception(tmp_path):
    with pytest.raises(RuntimeError):
        with fresh_output_directory(tmp_path / 'output'):
            raise RuntimeError('interrupted before output')
    with fresh_output_directory(tmp_path / 'output'):
        pass


@pytest.mark.parametrize('command', ['convert', 'muse'])
def test_single_run_preserves_patient_identity_and_midnight_intervals(tmp_path, command):
    inputs, output = tmp_path / 'inputs', tmp_path / 'output'
    make_xml(inputs / 'ecg20250831.xml', date='2025-08-31', time='23:50:00')
    make_xml(inputs / 'ecg20250901.xml', date='2025-09-01', time='00:10:00')
    make_xml(inputs / 'ecg20250902.xml', patient='SYN-B', date='2025-09-02')
    args = arguments(command, inputs, output) + ['--date-shift']
    start = 1
    if command == 'convert':
        start = 100
        args += ['--start-index', str(start)]
    run(command, args)
    objects = [pydicom.dcmread(p) for p in sorted(output.glob('*.dcm'))]
    assert [d.PatientID for d in objects] == [f'{start:06d}', f'{start:06d}', f'{start+1:06d}']
    times = [datetime.strptime(str(d.AcquisitionDateTime), '%Y%m%d%H%M%S') for d in objects]
    assert (times[1] - times[0]).total_seconds() == 20 * 60
    rows = json.loads((output / 'mrn_mapping_table.json').read_text())
    a = [row for row in rows.values() if row['original_mrn'] == 'SYN-A']
    assert len(a) == 2 and len({row['date_offset_days'] for row in a}) == 1
    assert all(row['mrn'] == f'{start:06d}' for row in a)


@pytest.mark.parametrize('start', [0, -1])
def test_invalid_start_index_is_refused_before_any_output(tmp_path, start):
    inputs = make_xml(tmp_path / 'inputs' / 'ecg20250817.xml')
    output = tmp_path / 'output'
    with pytest.raises(SystemExit) as exc:
        convert([str(inputs), '-o', str(output), '--start-index', str(start)])
    assert exc.value.code == 2
    assert not output.exists()


@pytest.mark.parametrize('label', ['Jane Smith', 'Rhythm Jane', 'Other'])
def test_untrusted_label_is_absent_from_deidentified_file(tmp_path, label):
    source = make_xml(tmp_path / 'input.xml', label=label)
    record = parse(source)
    untrusted_index = next(i for i, w in enumerate(record.waveforms)
                           if w.label not in ('Rhythm', 'Median'))
    original_label = record.waveforms[untrusted_index].label
    original_samples = record.waveforms[untrusted_index].leads['I'].copy()
    ds = build(record)
    assert 'MultiplexGroupLabel' not in ds.WaveformSequence[untrusted_index]
    assert [g.get('MultiplexGroupLabel') for g in ds.WaveformSequence].count(None) == 1
    assert all(g.get('MultiplexGroupLabel') in (None, 'Rhythm', 'Median') for g in ds.WaveformSequence)
    assert ds.PatientIdentityRemoved == 'YES'
    assert check_iod_constraints(ds) == []
    assert record.waveforms[untrusted_index].label == original_label
    assert (record.waveforms[untrusted_index].leads['I'] == original_samples).all()
    out = tmp_path / 'check.dcm'
    ds.save_as(str(out), write_like_original=False)
    back = pydicom.dcmread(out)
    assert 'MultiplexGroupLabel' not in back.WaveformSequence[untrusted_index]
    assert back.WaveformSequence[untrusted_index].WaveformData == ds.WaveformSequence[untrusted_index].WaveformData
    assert build(record, deidentify_record=False).WaveformSequence[untrusted_index].MultiplexGroupLabel == original_label


@pytest.mark.parametrize('command', ['convert', 'muse'])
def test_commands_clean_source_labels_in_default_and_shifted_mode(tmp_path, command):
    inputs = tmp_path / 'inputs'
    make_xml(inputs / 'ecg20250817.xml', label='Jane Smith')
    for suffix, mode in [('default', []), ('shifted', ['--date-shift'])]:
        output = tmp_path / suffix
        run(command, arguments(command, inputs, output) + mode)
        ds = pydicom.dcmread(next(output.glob('*.dcm')))
        assert [g.get('MultiplexGroupLabel') for g in ds.WaveformSequence].count(None) == 1
        assert all(g.get('MultiplexGroupLabel') in (None, 'Rhythm', 'Median') for g in ds.WaveformSequence)
        assert ds.PatientIdentityRemoved == 'YES'


@pytest.mark.parametrize('label,expected', [('rhythm', 'Rhythm'), (' MEDIAN ', 'Median')])
def test_writer_normalizes_safe_labels_without_changing_input(label, expected):
    rec = parse(EXAMPLE)
    rec.waveforms[0].label = label
    ds = build(rec)
    assert ds.WaveformSequence[0].MultiplexGroupLabel == expected
    assert rec.waveforms[0].label == label


@pytest.mark.parametrize('identified_first', [False, True])
def test_missing_patient_key_cannot_collide_with_a_source_patient_id(identified_first):
    table = SurrogateTable(date_shift=True, start_index=100)
    known = ('file:1', 'file:2')
    missing = (None, 'file:1')
    calls = [known, missing] if identified_first else [missing, known]
    first = table.lookup(*calls[0])
    second = table.lookup(*calls[1])
    assert first[0] != second[0]
    assert table.lookup(*calls[0]) == first
    assert table.lookup(*calls[1]) == second


@pytest.mark.parametrize('mode', [[], ['--date-shift']])
def test_muse_mapping_preserves_same_basename_in_different_folders(tmp_path, mode):
    inputs, output = tmp_path / 'inputs', tmp_path / 'output'
    make_xml(inputs / 'left' / 'ecg20250817.xml', patient='SYN-A')
    make_xml(inputs / 'right' / 'ecg20250817.xml', patient='SYN-B')
    muse_batch(arguments('muse', inputs, output) + mode)
    rows = json.loads((output / 'mrn_mapping_table.json').read_text())
    assert set(rows) == {'left/ecg20250817.xml', 'right/ecg20250817.xml'}
    assert len(list(output.rglob('*.dcm'))) == len(rows) == 2
    for key, row in rows.items():
        assert row['original_mrn'] == ('SYN-A' if key.startswith('left/') else 'SYN-B')
        out = output / row['ecg_dicom_file']
        assert out.exists()
        assert out.parent.name == Path(key).parent.name
        ds = pydicom.dcmread(out)
        assert ds.PatientID == row['mrn']
        if mode:
            original = datetime(2025, 8, 17)
            shifted = datetime.strptime(str(ds.StudyDate), '%Y%m%d')
            assert (shifted - original).days == row['date_offset_days']


@pytest.mark.parametrize('mode', [[], ['--date-shift'], ['--keep-identity']])
def test_multi_format_preserves_objects_when_stems_and_suffixes_collide(tmp_path, mode):
    inputs, output = tmp_path / 'inputs', tmp_path / 'output'
    sources = [make_xml(inputs / 'left' / 'record.xml', patient='SYN-A'),
               make_xml(inputs / 'right' / 'record.xml', patient='SYN-B'),
               make_xml(inputs / 'right' / 'record_2.xml', patient='SYN-C')]
    assert convert([str(inputs), '-r', '-o', str(output)] + mode) == 0
    objects = list(output.glob('*.dcm'))
    assert len(objects) == 3
    assert len({pydicom.dcmread(p).PatientID for p in objects}) == 3
    if '--keep-identity' in mode:
        assert not (output / 'mrn_mapping_table.json').exists()
        return
    rows = json.loads((output / 'mrn_mapping_table.json').read_text())
    assert set(rows) == {str(p.resolve()) for p in sources}
    assert len({row['ecg_dicom_file'] for row in rows.values()}) == 3
    for row in rows.values():
        ds = pydicom.dcmread(output / row['ecg_dicom_file'])
        assert ds.PatientID == row['mrn']
        if mode:
            assert (datetime.strptime(str(ds.StudyDate), '%Y%m%d') - datetime(2025, 8, 17)).days == row['date_offset_days']


def test_duplicate_source_path_is_converted_once(tmp_path):
    source = make_xml(tmp_path / 'input.xml')
    output = tmp_path / 'output'
    assert convert([str(source), str(source.resolve()), '-o', str(output)]) == 0
    assert len(list(output.glob('*.dcm'))) == 1
    rows = json.loads((output / 'mrn_mapping_table.json').read_text())
    assert len(rows) == 1


def test_failed_save_does_not_create_a_mapping_row(tmp_path, monkeypatch):
    inputs, output = tmp_path / 'inputs', tmp_path / 'output'
    make_xml(inputs / 'bad.xml', patient='SYN-A')
    good = make_xml(inputs / 'good.xml', patient='SYN-B')
    real_save = pydicom.dataset.FileDataset.save_as
    def fail_one(self, filename, *args, **kwargs):
        if Path(filename).name == 'bad.dcm':
            raise OSError('simulated write failure')
        return real_save(self, filename, *args, **kwargs)
    monkeypatch.setattr(pydicom.dataset.FileDataset, 'save_as', fail_one)
    assert convert([str(inputs), '-o', str(output)]) == 1
    rows = json.loads((output / 'mrn_mapping_table.json').read_text())
    assert set(rows) == {str(good.resolve())}
    assert len(list(output.glob('*.dcm'))) == len(rows) == 1


def test_mapping_rejects_duplicate_key_without_overwriting_a_row():
    table = SurrogateTable(date_shift=True)
    table.record('left/record.xml', 'first.dcm', 'SYN-A', '000001', -400)
    before = dict(table.rows)
    with pytest.raises(ValueError, match='already has a mapping'):
        table.record('left/record.xml', 'second.dcm', 'SYN-B', '000002', -500)
    assert table.rows == before

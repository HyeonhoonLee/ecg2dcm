"""Per-format attribute coverage from converted DICOM objects. Aggregate counts only."""
import sys, glob, os, json
import pydicom

ROWS = [
    ('Patient',                 "Patient's Sex (0010,0040)",                       lambda d: d.get('PatientSex')),
    ('Patient Study',           "Patient's Age (0010,1010)",                       lambda d: d.get('PatientAge')),
    ('General Study',           'Study Date / Time (0008,0020/0030)',              lambda d: d.get('StudyDate') and d.get('StudyTime')),
    ('Waveform Identification', 'Acquisition DateTime (0008,002A)',                lambda d: d.get('AcquisitionDateTime')),
    ('General Equipment',       'Manufacturer (0008,0070)',                        lambda d: d.get('Manufacturer')),
    ('General Equipment',       "Manufacturer's Model Name (0008,1090)",           lambda d: d.get('ManufacturerModelName')),
    ('General Equipment',       'Software Versions (0018,1020)',                   lambda d: d.get('SoftwareVersions')),
    ('Waveform',                'Multiplex Group Label (003A,0020)',               lambda d: _wf(d, 'MultiplexGroupLabel')),
    ('Waveform',                'Sampling Frequency (003A,001A)',                  lambda d: _wf(d, 'SamplingFrequency')),
    ('Waveform',                'Channel Source Sequence (003A,0208)',             lambda d: _ch(d, 'ChannelSourceSequence')),
    ('Waveform',                'Channel Sensitivity Correction Factor (003A,0212)', lambda d: _ch(d, 'ChannelSensitivityCorrectionFactor')),
    ('Waveform',                'Filter Low Frequency (003A,0220)',                lambda d: _ch(d, 'FilterLowFrequency')),
    ('Waveform',                'Filter High Frequency (003A,0221)',               lambda d: _ch(d, 'FilterHighFrequency')),
    ('Waveform',                'Notch Filter Frequency (003A,0222)',              lambda d: _ch(d, 'NotchFilterFrequency')),
    ('Acquisition Context',     'Acquisition Context Sequence (0040,0555)',        lambda d: d.get('AcquisitionContextSequence')),
    ('Waveform Annotation',     'Waveform Annotation Sequence (0040,B020)',        lambda d: d.get('WaveformAnnotationSequence')),
]

def _wf(d, name):
    seq = d.get('WaveformSequence')
    return seq[0].get(name) if seq else None

def _ch(d, name):
    seq = d.get('WaveformSequence')
    if not seq: return None
    ch = seq[0].get('ChannelDefinitionSequence')
    return ch[0].get(name) if ch else None

def _present(v):
    if v is None: return False
    if isinstance(v, pydicom.sequence.Sequence): return len(v) > 0
    if isinstance(v, (list, pydicom.multival.MultiValue)): return len(v) > 0 and any(str(x).strip() for x in v)
    return str(v).strip() != ''

def run(label, files):
    n = len(files)
    counts = [0] * len(ROWS)
    for f in files:
        d = pydicom.dcmread(f, stop_before_pixels=True)
        for i, (_, _, fn) in enumerate(ROWS):
            try:
                if _present(fn(d)): counts[i] += 1
            except Exception:
                pass
    return label, n, counts

if __name__ == '__main__':
    out = {}
    for spec in sys.argv[1:]:
        label, pattern = spec.split('=', 1)
        files = sorted(glob.glob(pattern))
        if not files:
            print(f'!! no files for {label}: {pattern}', file=sys.stderr); continue
        label, n, counts = run(label, files)
        out[label] = {'n': n, 'counts': counts}
    labels = list(out)
    print('| Module | Attribute | ' + ' | '.join(f'{l} (n={out[l]["n"]})' for l in labels) + ' |')
    print('|---|---|' + '---|' * len(labels))
    for i, (mod, attr, _) in enumerate(ROWS):
        cells = []
        for l in labels:
            c, n = out[l]['counts'][i], out[l]['n']
            cells.append('all' if c == n else ('-' if c == 0 else f'{c}/{n}'))
        print(f'| {mod} | {attr} | ' + ' | '.join(cells) + ' |')
    json.dump(out, open('coverage_matrix.json', 'w'), indent=1)

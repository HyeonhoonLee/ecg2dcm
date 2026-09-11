"""Content constraints of the General ECG IOD that attribute-level validators do not check.

dicom-validator and DVTk verify that the modules of an IOD are present, that
each attribute has the right VR and type, and that conditional requirements
are met. They do not evaluate the IOD's own content constraints in PS3.3
Section A.34.4.4 (General ECG IOD), which bound the number of multiplex groups,
the channels per group, the sampling frequency and the sample interpretation,
and which make CID 3001 "ECG Lead" a Defined (not merely Baseline) context group
for Channel Source Sequence. The 12-Lead ECG IOD (A.34.3.4) additionally caps
the total number of channels across all groups at 13, which is what excludes a
rhythm group and a median group of twelve channels each from that IOD and why
this package writes General ECG Waveform Storage.

:func:`check_iod_constraints` returns a list of violations, empty when the
object satisfies every constraint it knows about. It is run on every object
in the package's own tests and in the corpus-level validation scripts.
"""
from typing import List

from .codes import CID_3001_CODE_VALUES, SOP_GENERAL_ECG, SOP_TWELVE_LEAD_ECG

TEMPORAL_RANGE_TYPES = {'POINT', 'MULTIPOINT', 'SEGMENT', 'MULTISEGMENT', 'BEGIN', 'END'}


def _num(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def check_iod_constraints(ds) -> List[str]:
    """Return the General ECG IOD content constraints (PS3.3 A.34.4.4) that ``ds`` violates."""
    out: List[str] = []
    sop = str(ds.get('SOPClassUID', ''))
    if sop == SOP_TWELVE_LEAD_ECG:
        limits = dict(items=(1, 5), channels=(1, 13), total=13, samples=16384, name='12-Lead ECG IOD')
    elif sop == SOP_GENERAL_ECG:
        limits = dict(items=(1, 4), channels=(1, 24), total=None, samples=None, name='General ECG IOD')
    else:
        return [f'SOP Class UID {sop!r} is neither General ECG nor 12-Lead ECG Waveform Storage']

    if str(ds.get('Modality', '')) != 'ECG':
        out.append('A.34.4.4.1: Modality (0008,0060) shall be ECG')

    groups = list(ds.get('WaveformSequence', []) or [])
    lo, hi = limits['items']
    if not (lo <= len(groups) <= hi):
        out.append(f'A.34.4.4.2: {len(groups)} Waveform Sequence Items; {limits["name"]} allows {lo} to {hi}')

    total = 0
    for i, g in enumerate(groups, start=1):
        n_ch = int(g.get('NumberOfWaveformChannels', 0) or 0)
        n_s = int(g.get('NumberOfWaveformSamples', 0) or 0)
        total += n_ch
        lo, hi = limits['channels']
        if not (lo <= n_ch <= hi):
            out.append(f'A.34.4.4.3: group {i} has {n_ch} channels; allowed {lo} to {hi}')
        defs = list(g.get('ChannelDefinitionSequence', []) or [])
        if len(defs) != n_ch:
            out.append(f'group {i}: Number of Waveform Channels {n_ch} but {len(defs)} Channel Definition items')
        fs = _num(g.get('SamplingFrequency'))
        if fs is None or not (200.0 <= fs <= 1000.0):
            out.append(f'A.34.4.4.4: group {i} Sampling Frequency {fs}; allowed 200 to 1000')
        if str(g.get('WaveformSampleInterpretation', '')) != 'SS':
            out.append(f'A.34.4.4.6: group {i} Waveform Sample Interpretation shall be SS')
        if limits['samples'] and n_s > limits['samples']:
            out.append(f'A.34.3.4.5: group {i} has {n_s} samples; allowed at most {limits["samples"]}')
        data = g.get('WaveformData', b'') or b''
        bits = int(g.get('WaveformBitsAllocated', 16) or 16)
        expect = n_ch * n_s * (bits // 8)
        if len(data) != expect:
            out.append(f'group {i}: Waveform Data is {len(data)} bytes, expected {expect} for {n_ch}x{n_s}x{bits} bits')
        for j, c in enumerate(defs, start=1):
            src = list(c.get('ChannelSourceSequence', []) or [])
            if not src:
                out.append(f'group {i} channel {j}: Channel Source Sequence absent')
                continue
            code = src[0]
            scheme, value = str(code.get('CodingSchemeDesignator', '')), str(code.get('CodeValue', ''))
            if scheme != 'MDC' or value not in CID_3001_CODE_VALUES:
                out.append(f'A.34.4.4.5: group {i} channel {j} source ({value}, {scheme}) is not in DCID 3001 "ECG Lead"')
    if limits['total'] and total > limits['total']:
        out.append(f'A.34.3.4.4: {total} channels across all groups; the 12-Lead ECG IOD allows at most {limits["total"]}')

    # Waveform Annotation references must point at existing groups, channels and samples.
    for k, a in enumerate(ds.get('WaveformAnnotationSequence', []) or [], start=1):
        refs = list(a.get('ReferencedWaveformChannels', []) or [])
        if len(refs) < 2 or len(refs) % 2:
            out.append(f'annotation {k}: Referenced Waveform Channels must be (group, channel) pairs')
            continue
        pairs = list(zip(refs[0::2], refs[1::2]))
        for m, c in pairs:
            if not (1 <= int(m) <= len(groups)):
                out.append(f'annotation {k}: references multiplex group {m}, object has {len(groups)}')
                continue
            n_ch = int(groups[int(m) - 1].get('NumberOfWaveformChannels', 0) or 0)
            if int(c) != 0 and not (1 <= int(c) <= n_ch):
                out.append(f'annotation {k}: references channel {c} of group {m}, which has {n_ch}')
        trt = a.get('TemporalRangeType')
        if trt is not None:
            trt = str(trt)
            if trt not in TEMPORAL_RANGE_TYPES:
                out.append(f'annotation {k}: Temporal Range Type {trt!r} is not an enumerated value')
            pos = list(a.get('ReferencedSamplePositions', []) or [])
            if trt == 'SEGMENT' and len(pos) != 2:
                out.append(f'annotation {k}: SEGMENT needs exactly two sample positions, has {len(pos)}')
            if trt == 'POINT' and len(pos) != 1:
                out.append(f'annotation {k}: POINT needs exactly one sample position, has {len(pos)}')
            n_s = max((int(groups[int(m) - 1].get('NumberOfWaveformSamples', 0) or 0)
                       for m, _ in pairs if 1 <= int(m) <= len(groups)), default=0)
            for p in pos:
                if not (1 <= int(p) <= n_s):
                    out.append(f'annotation {k}: sample position {p} outside 1..{n_s}')
    return out

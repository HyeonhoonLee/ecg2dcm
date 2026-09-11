#!/usr/bin/env python3
"""Supplementary Table 9: acquisition device and software profile of the study corpus.

Run this on the institution's own GE MUSE XML export. It reads only the
<TestDemographics> and <Waveform> headers, never the waveform payload, and writes
no patient-level output: every table is an aggregate count.

Standard library only; no installation needed.

    python3 supp_table9_device_profile.py --xml-dir /path/to/muse_xml --out supp_table9
    python3 supp_table9_device_profile.py --zip   /path/to/muse_xml.zip --out supp_table9

The --zip form streams each entry straight out of the archive, so a multi-gigabyte
export never has to be extracted to disk. Start with --limit 1000 to check the
values before running the whole corpus.

Produces:
    supp_table9_device.csv      AcquisitionDevice x count, patients, date range
    supp_table9_software.csv    AcquisitionSoftwareVersion x AnalysisSoftwareVersion
    supp_table9_location.csv    SiteName / LocationName / RoomID
    supp_table9_acquisition.csv SampleBase, NumberofLeads, filters, DataType
    supp_table9_summary.txt     one-paragraph summary for the manuscript
"""
import argparse, csv, collections, os, sys, glob, zipfile, io, re
import xml.etree.ElementTree as ET

FIELDS_TEST = ['AcquisitionDevice', 'AcquisitionSoftwareVersion', 'AnalysisSoftwareVersion',
               'SiteName', 'LocationName', 'RoomID', 'DataType', 'AcquisitionDate']
FIELDS_WAVE = ['SampleBase', 'NumberofLeads', 'HighPassFilter', 'LowPassFilter', 'ACFilter']

def text(el, tag):
    if el is None: return None
    n = el.find(tag)
    return n.text.strip() if n is not None and n.text and n.text.strip() else None

_TAG_CACHE = {}

def _rx(tag):
    if tag not in _TAG_CACHE:
        _TAG_CACHE[tag] = re.compile(rf'<{tag}>([^<]*)</{tag}>')
    return _TAG_CACHE[tag]


def _extract_head(blob, name):
    """Read the fields from the leading bytes of a record.

    Every field this script needs sits in the first few kilobytes of a MUSE
    export, ahead of the base64 waveform payload, so decoding the whole record
    is unnecessary. Returns None if any required marker is absent, in which
    case the caller falls back to a full parse.
    """
    try:
        t = blob.decode('utf-8')
    except UnicodeDecodeError:
        t = blob.decode('latin-1')
    if '<RestingECG' not in t:
        return None
    # the waveform block must be present in the head, or the filter and
    # sample-rate fields would be silently reported as absent
    if '<Waveform>' not in t or '<SampleBase>' not in t:
        return None
    first = lambda tag: (_rx(tag).search(t).group(1).strip() or None) if _rx(tag).search(t) else None
    rec = {'file': name}
    for k in FIELDS_TEST + FIELDS_WAVE:
        rec[k] = first(k)
    rec['PatientID'] = first('PatientID')
    # The second waveform block sits behind the first block's base64 payload and
    # is therefore often outside the head window. Reporting the types seen here
    # would undercount them, so leave it unassessed in head mode.
    rec['WaveformTypes'] = None
    return rec


def _extract(root, name):
    rec = {'file': name}
    test = root.find('TestDemographics')
    for k in FIELDS_TEST: rec[k] = text(test, k)
    pat = root.find('PatientDemographics')
    rec['PatientID'] = text(pat, 'PatientID')
    wf = next(root.iter('Waveform'), None)
    for k in FIELDS_WAVE: rec[k] = text(wf, k)
    rec['WaveformTypes'] = ','.join(sorted({(text(w, 'WaveformType') or '?') for w in root.iter('Waveform')}))
    return rec


def iter_zip(zip_path, limit=None, head_bytes=32768):
    """Stream XML entries out of a zip archive without extracting it."""
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist()
                 if n.lower().endswith('.xml') and not n.endswith('/')
                 and not os.path.basename(n).startswith('._')]
        names.sort()
        if limit: names = names[:limit]
        print(f'  {len(names)} XML entries in {os.path.basename(zip_path)}', file=sys.stderr)
        for n in names:
            base = os.path.basename(n)
            try:
                if head_bytes:
                    with zf.open(n) as fh:
                        rec = _extract_head(fh.read(head_bytes), base)
                    if rec is not None:
                        yield rec; continue
                with zf.open(n) as fh:
                    root = ET.parse(fh).getroot()
            except Exception as e:
                yield {'file': base, 'parse_error': type(e).__name__}
                continue
            yield _extract(root, base)


def iter_headers(xml_dir, limit=None):
    """Yield one dict per file, parsing incrementally and stopping before waveform data."""
    files = sorted(glob.glob(os.path.join(xml_dir, '**', '*.xml'), recursive=True)) + \
            sorted(glob.glob(os.path.join(xml_dir, '**', '*.XML'), recursive=True))
    if limit: files = files[:limit]
    for f in files:
        rec = {'file': os.path.basename(f)}
        try:
            root = ET.parse(f).getroot()
        except Exception as e:
            rec['parse_error'] = type(e).__name__
            yield rec; continue
        test = root.find('TestDemographics')
        for k in FIELDS_TEST: rec[k] = text(test, k)
        pat = root.find('PatientDemographics')
        rec['PatientID'] = text(pat, 'PatientID')
        wf = next(root.iter('Waveform'), None)
        for k in FIELDS_WAVE: rec[k] = text(wf, k)
        rec['WaveformTypes'] = ','.join(sorted({(text(w, 'WaveformType') or '?') for w in root.iter('Waveform')}))
        yield rec

def write_csv(path, header, rows):
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh); w.writerow(header); w.writerows(rows)
    print(f'  wrote {path} ({len(rows)} rows)')

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--xml-dir', help='directory of MUSE XML files (searched recursively)')
    src.add_argument('--zip', dest='zip_path', help='zip archive of MUSE XML files, read without extracting')
    ap.add_argument('--out', default='supp_table9', help='output prefix')
    ap.add_argument('--limit', type=int, default=None, help='process only the first N files (start with 1000)')
    ap.add_argument('--since', metavar='YYYY-MM',
                    help='keep only records acquired in or after this month (AcquisitionDate)')
    ap.add_argument('--until', metavar='YYYY-MM',
                    help='keep only records acquired in or before this month (AcquisitionDate)')
    ap.add_argument('--head-bytes', type=int, default=32768,
                    help='read only this many leading bytes of each record (0 to always parse in full). '
                         'Every field used here precedes the waveform payload, and a record whose head '
                         'lacks a required marker is re-read in full.')
    a = ap.parse_args()
    source = (iter_zip(a.zip_path, a.limit, a.head_bytes) if a.zip_path
              else iter_headers(a.xml_dir, a.limit))

    def ym(d):
        """MUSE AcquisitionDate is MM-DD-YYYY; return YYYY-MM, or None if unparseable."""
        try:
            mm, _dd, yyyy = d.split('-')
            return f'{yyyy}-{mm}'
        except Exception:
            return None

    n = 0; errs = 0; skipped_window = 0; skipped_nodate = 0
    dev = collections.Counter(); dev_pat = collections.defaultdict(set); dev_dates = collections.defaultdict(list)
    sw = collections.Counter(); loc = collections.Counter(); acq = collections.Counter()
    dtype = collections.Counter(); wtypes = collections.Counter(); patients = set()

    for rec in source:
        n += 1
        if rec.get('parse_error'): errs += 1; continue
        if a.since or a.until:
            m = ym(rec.get('AcquisitionDate') or '')
            if m is None:
                skipped_nodate += 1; continue
            if (a.since and m < a.since) or (a.until and m > a.until):
                skipped_window += 1; continue
        d = rec.get('AcquisitionDevice') or '(element absent)'
        dev[d] += 1
        if rec.get('PatientID'):
            dev_pat[d].add(rec['PatientID']); patients.add(rec['PatientID'])
        if rec.get('AcquisitionDate'): dev_dates[d].append(rec['AcquisitionDate'])
        sw[(rec.get('AcquisitionSoftwareVersion') or '(absent)', rec.get('AnalysisSoftwareVersion') or '(absent)')] += 1
        loc[(rec.get('SiteName') or '(absent)', rec.get('LocationName') or '(absent)', rec.get('RoomID') or '(absent)')] += 1
        acq[(rec.get('SampleBase') or '?', rec.get('NumberofLeads') or '?', rec.get('HighPassFilter') or '?',
             rec.get('LowPassFilter') or '?', rec.get('ACFilter') or '?')] += 1
        dtype[rec.get('DataType') or '(absent)'] += 1
        wtypes[rec.get('WaveformTypes')] += 1
        if n % 20000 == 0: print(f'  ... {n} files', file=sys.stderr)

    kept = n - errs - skipped_window - skipped_nodate

    def span(ds):
        if not ds: return ''
        try:
            ys = sorted(f'{x.split("-")[2]}-{x.split("-")[0]}' for x in ds if x.count('-') == 2)
            return f'{ys[0]} to {ys[-1]}' if ys else ''
        except Exception: return ''

    # deterministic: count descending, ties broken by key, so the same corpus
    # always produces byte-identical tables whatever order the files arrive in
    rank = lambda counter: sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))

    write_csv(f'{a.out}_device.csv', ['AcquisitionDevice','ECGs','%','Patients','DateRange'],
              [[d, c, f'{c/max(kept,1)*100:.2f}', len(dev_pat[d]) or '', span(dev_dates[d])]
               for d, c in rank(dev)])
    write_csv(f'{a.out}_software.csv', ['AcquisitionSoftwareVersion','AnalysisSoftwareVersion','ECGs','%'],
              [[x, y, c, f'{c/max(kept,1)*100:.2f}'] for (x, y), c in rank(sw)])
    write_csv(f'{a.out}_location.csv', ['SiteName','LocationName','RoomID','ECGs'],
              [[s, l, r, c] for (s, l, r), c in rank(loc)])
    write_csv(f'{a.out}_acquisition.csv',
              ['SampleBase','NumberofLeads','HighPassFilter','LowPassFilter','ACFilter','ECGs'],
              [[*k, c] for k, c in rank(acq)])

    with open(f'{a.out}_summary.txt', 'w', encoding='utf-8') as fh:
        fh.write(f'Files scanned: {n}\nParse errors: {errs}\n')
        if a.since or a.until:
            fh.write(f'Acquisition window: {a.since or "(open)"} to {a.until or "(open)"}\n')
            fh.write(f'  excluded, outside window: {skipped_window}\n')
            fh.write(f'  excluded, no usable AcquisitionDate: {skipped_nodate}\n')
        fh.write(f'Records tabulated: {kept}\nDistinct patients (PatientID): {len(patients)}\n\n')
        named = [d for d in dev if d != '(element absent)']
        fh.write(f'Distinct AcquisitionDevice values: {len(named)} named'
                 + (f' + {dev["(element absent)"]} records with no AcquisitionDevice element' if '(element absent)' in dev else '')
                 + '\n')
        for d, c in rank(dev): fh.write(f'  {d}: {c} ({c/max(kept,1)*100:.2f}%)\n')
        n_acq = len({x for x, _ in sw} - {'(absent)'})
        n_ana = len({y for _, y in sw} - {'(absent)'})
        fh.write(f'\nDistinct acquisition software versions: {n_acq} named'
                 + (' + records with the element absent' if any(x == '(absent)' for x, _ in sw) else '') + '\n')
        fh.write(f'Distinct analysis software versions: {n_ana} named'
                 + (' + records with the element absent' if any(y == '(absent)' for _, y in sw) else '') + '\n')
        fh.write(f'Distinct SiteName values: {len({s for s, _, _ in loc})}\n')
        fh.write(f'Distinct LocationName values: {len({l for _, l, _ in loc})}\n')
        fh.write(f'Distinct RoomID values: {len({r for _, _, r in loc} - {"(absent)"})} named\n')
        fh.write(f'Distinct LocationName/RoomID pairs: {len({(l, r) for _, l, r in loc})}\n')
        fh.write(f'\nSampleBase distribution: {dict(collections.Counter(k[0] for k in acq.elements()))}\n')
        fh.write(f'NumberofLeads distribution: {dict(collections.Counter(k[1] for k in acq.elements()))}\n')
        fh.write(f'DataType distribution: {dict(dtype)}\n')
        assessed = {k: v for k, v in wtypes.items() if k}
        na = wtypes.get(None, 0)
        fh.write(f'WaveformType combinations: {assessed}'
                 + (f'  [assessed for {sum(assessed.values())} of {kept} records; '
                    f'{na} were read in head mode, where the second waveform block lies beyond the '
                    f'window. Rerun with --head-bytes 0 for a complete count.]' if na else '')
                 + '\n')
        fh.write('\nSentence for the manuscript (fill the bracketed values):\n')
        fh.write(f'  "The {kept} records were acquired on {len(named)} device models with '
                 f'{n_acq} acquisition software versions and {n_ana} analysis software versions, at '
                 f'{len({l for _, l, _ in loc})} recording locations '
                 f'({len({(l, r) for _, l, r in loc})} distinct location/room pairs)."\n')
    print(f'  wrote {a.out}_summary.txt')
    named = [d for d in dev if d != '(element absent)']
    print(f'\nScanned {n} files ({errs} parse errors), tabulated {kept}, '
          f'{len(named)} named device models, {len(patients)} patients.')

if __name__ == '__main__':
    main()

"""Convert open WFDB datasets through the WFDB front end and validate the output.

These datasets were acquired at other institutions on other manufacturers'
equipment and published after conversion to WFDB, so this exercises the mapping
and writing stages against data of other origins. It does not exercise native
vendor-format parsing.

Two columns are reported for each dataset because WFDB carries no acquisition
instant unless the header supplies a base date, and Content Date (0008,0023) and
Acquisition DateTime (0008,002A) are Type 1:

  as distributed        converted using only what the distributed files contain
  date supplied         converted after the caller supplies an acquisition
                        instant, from the dataset's own metadata table where one
                        exists, otherwise a fixed placeholder. This isolates
                        whether the rest of the mapping is sound from whether
                        the distribution carries the date.

    uv run run_wfdb.py --out wfdb_results.json

The defaults point at the durable mirror under ~/Projects/Data; pass --root and
--mimic to read from somewhere else.
"""
import argparse
import csv
import glob
import json
import logging
import multiprocessing as mp
import os
import sys
from pathlib import Path

from ecg2dcm.adapters import wfdb                                    # noqa: E402
from ecg2dcm import writer, check_iod_constraints                    # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stratified_conversion import required_attributes, completeness  # noqa: E402

from dicom_validator.spec_reader.edition_reader import EditionReader  # noqa: E402
from dicom_validator.validator.iod_validator import IODValidator      # noqa: E402

# A date the source does not carry. Used only for the "date supplied" column, so
# that the effect of the missing acquisition instant can be separated from the
# rest of the mapping. It is never presented as the true acquisition date.
PLACEHOLDER_DATE = '20000101'
PLACEHOLDER_TIME = '000000'


def ptbxl_dates(root):
    """PTB-XL records the acquisition instant in ptbxl_database.csv."""
    path = Path(root, 'ptbxl_database.csv')
    if not path.exists():
        return {}
    out = {}
    with open(path, newline='', encoding='utf-8') as fh:
        for row in csv.DictReader(fh):
            stamp = (row.get('recording_date') or '').strip()
            fname = (row.get('filename_hr') or '').strip()
            if not stamp or not fname:
                continue
            date, _, time = stamp.partition(' ')
            d = date.replace('-', '')
            t = time.replace(':', '')[:6] or '000000'
            if len(d) == 8 and d.isdigit():
                out[os.path.basename(fname)] = (d, t.ljust(6, '0'))
    return out


# Worker globals, set once per process by _init.
_W = {}


def _init(standard):
    logging.disable(logging.CRITICAL)
    _W['info'] = EditionReader.load_dicom_info(Path(standard))
    _W['required'] = required_attributes(standard)


def _chunk(args):
    """Score one slice of a dataset in its own process."""
    heas, dates = args
    return run('', heas, _W['info'], _W['required'], dates, _quiet=True)


def _merge(a, b):
    for k in ('as_distributed', 'date_supplied'):
        for f in a[k]:
            a[k][f] += b[k][f]
    a['records'] += b['records']
    a['with_source_date'] += b['with_source_date']
    for k in ('reasons', 'leads', 'fs'):
        for key, v in b[k].items():
            a[k][key] = a[k].get(key, 0) + v
    return a


def run(name, heas, info, required, dates=None, _quiet=False):
    dates = dates or {}
    res = {'dataset': name, 'records': len(heas),
           'as_distributed': {'converted': 0, 'conformant': 0, 'complete': 0, 'constrained': 0},
           'date_supplied': {'converted': 0, 'conformant': 0, 'complete': 0, 'constrained': 0},
           'with_source_date': 0, 'reasons': {}, 'leads': {}, 'fs': {}}

    def score(rec, bucket):
        try:
            ds = writer.build(rec, index=1)
        except Exception as e:
            res['reasons'][str(e)[:70]] = res['reasons'].get(str(e)[:70], 0) + 1
            return
        bucket['converted'] += 1
        out = IODValidator(ds, info, logging.CRITICAL).validate()
        if sum(len(t) or 1 for m, f in out.items() if m != 'fatal' for t in f.values()) == 0:
            bucket['conformant'] += 1
        if not completeness(ds, required):
            bucket['complete'] += 1
        if not check_iod_constraints(ds):
            bucket['constrained'] += 1

    for h in heas:
        key = os.path.basename(h)[:-4]
        d, t = dates.get(key, (None, None))
        try:
            rec = wfdb.parse(h, acquisition_date=d, acquisition_time=t)
        except Exception as e:
            res['reasons'][f'{type(e).__name__}: {str(e)[:60]}'] = \
                res['reasons'].get(f'{type(e).__name__}: {str(e)[:60]}', 0) + 1
            continue
        w = rec.waveforms[0]
        res['leads'][str(len(w.leads))] = res['leads'].get(str(len(w.leads)), 0) + 1
        res['fs'][str(int(w.sampling_frequency))] = res['fs'].get(str(int(w.sampling_frequency)), 0) + 1
        if rec.acquisition_date:
            res['with_source_date'] += 1
        score(rec, res['as_distributed'])
        if not rec.acquisition_date:
            rec.acquisition_date, rec.acquisition_time = PLACEHOLDER_DATE, PLACEHOLDER_TIME
        score(rec, res['date_supplied'])
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', default=os.path.expanduser('~/Projects/Data/ECG/physionet.org/files'),
                    help='PhysioNet mirror root holding <project>/<version>/ directories')
    ap.add_argument('--mimic', default=os.path.expanduser(
                        '~/Projects/Data/MIMIC-IV-2.2/physionet.org/files/mimic-iv-ecg/1.0'),
                    help='MIMIC-IV-ECG mirror, which lives with the rest of the MIMIC-IV family')
    ap.add_argument('--limit', type=int, default=None, help='cap records per dataset')
    ap.add_argument('--only', help='comma-separated subset of ptbxl,ecgdmmld,arr,ludb,mimic')
    ap.add_argument('--mimic-stride', type=int, default=0,
                    help='0 (the default) uses the whole mirror, which now holds all 800,035 '
                         'records. A positive N takes every Nth record of the published '
                         'record_list.csv instead, which is how to get a reproducible number '
                         'out of a mirror that is only partly populated.')
    ap.add_argument('--mimic-limit', type=int, default=10000,
                    help='cap the strided MIMIC sample at this many records (ignored when '
                         '--mimic-stride is 0)')
    ap.add_argument('--out', default='wfdb_results.json')
    ap.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 2) - 2),
                    help='processes per dataset (1 disables parallelism)')
    ap.add_argument('--standard', default=str(Path.home() / 'dicom-validator' / '2024b' / 'json'))
    a = ap.parse_args()

    info = EditionReader.load_dicom_info(Path(a.standard))
    required = required_attributes(a.standard)
    logging.disable(logging.CRITICAL)

    def heas(d):
        out = sorted(glob.glob(os.path.join(d, '**', '*.hea'), recursive=True))
        return out[:a.limit] if a.limit else out

    def mimic_heas():
        """The stated sample, not whatever happens to be on disk.

        Every Nth record of the published record_list.csv, in its distributed
        order. Records not yet mirrored are skipped and counted, so the run
        reports how much of the intended sample it actually covered."""
        if not a.mimic_stride:
            return heas(os.path.join(a.mimic, 'files'))
        table = Path(a.mimic, 'record_list.csv')
        if not table.exists():
            return heas(os.path.join(a.mimic, 'files'))
        with open(table, newline='', encoding='utf-8') as fh:
            paths = [r['path'].strip() for r in csv.DictReader(fh) if r.get('path')]
        want = paths[::a.mimic_stride]
        if a.mimic_limit:
            want = want[:a.mimic_limit]
        out, absent = [], 0
        for r in want:
            h = os.path.join(a.mimic, r + '.hea')
            if os.path.exists(h) and os.path.exists(h[:-4] + '.dat'):
                out.append(h)
            else:
                absent += 1
        if absent:
            print(f'  MIMIC sample: {len(out)} of {len(want)} present, {absent} not yet mirrored',
                  file=sys.stderr)
        return out

    want = {x.strip() for x in a.only.split(',')} if a.only else None
    # Only the 500 Hz set of PTB-XL and only the rhythm records of ECGDMMLD are
    # read; both projects also ship a second copy at another rate or as medians.
    datasets = [
        ('ptbxl', 'PTB-XL (Physikalisch-Technische Bundesanstalt, Germany; Schiller)',
         os.path.join(a.root, 'ptb-xl', '1.0.3', 'records500'),
         ptbxl_dates(os.path.join(a.root, 'ptb-xl', '1.0.3'))),
        ('ecgdmmld', 'ECGDMMLD (Spaulding Clinical, United States; Mortara)',
         os.path.join(a.root, 'ecgdmmld', '1.0.0', 'raw'), {}),
        ('arr', 'Chapman-Shaoxing and Ningbo (two Chinese hospitals; GE MUSE)',
         os.path.join(a.root, 'ecg-arrhythmia', '1.0.0'), {}),
        ('ludb', 'LUDB (Lobachevsky University, Russia; Schiller Cardiovit AT-101)',
         os.path.join(a.root, 'ludb', '1.0.1', 'data'), {}),
        # MIMIC-IV-ECG writes the acquisition instant into the WFDB header itself,
        # so no sidecar table is needed. The dates are shifted into the future by
        # the publisher's de-identification and are surrogates, not real dates.
        ('mimic', 'MIMIC-IV-ECG (Beth Israel Deaconess Medical Center, United States)',
         None, {}),
    ]

    results = []
    for key, name, d, dates in datasets:
        if want and key not in want:
            continue
        hs = mimic_heas() if key == 'mimic' else heas(d)
        if not hs:
            print(f'  skipping {name}: no .hea files found', file=sys.stderr)
            continue
        print(f'  {name}: {len(hs)} records', file=sys.stderr)
        if a.workers > 1 and len(hs) > 4 * a.workers:
            # 800,035 MIMIC records at roughly 10 ms each is over two hours in
            # one process. Slice the record list and merge the counters.
            size = (len(hs) + a.workers - 1) // a.workers
            slices = [(hs[i:i + size], dates) for i in range(0, len(hs), size)]
            ctx = mp.get_context('spawn')
            with ctx.Pool(a.workers, initializer=_init, initargs=(a.standard,)) as pool:
                parts = pool.map(_chunk, slices)
            merged = parts[0]
            for q in parts[1:]:
                merged = _merge(merged, q)
            merged['dataset'] = name
            results.append(merged)
        else:
            results.append(run(name, hs, info, required, dates))
        r = results[-1]
        print(f'    as distributed {r["as_distributed"]["conformant"]}/{r["records"]}, '
              f'date supplied {r["date_supplied"]["conformant"]}/{r["records"]}', file=sys.stderr)

    logging.disable(logging.NOTSET)
    with open(a.out, 'w', encoding='utf-8') as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    print(f'wrote {a.out}')


if __name__ == '__main__':
    main()

"""``ecg2dcm-convert``: convert any supported ECG file (or directory) to DICOM.

Formats are detected from the file content: GE MUSE, GE CardioSoft, Philips
Sierra, HL7 aECG, Mortara ELI Link, Schiller SEMA and WFDB (``.hea``). Each
input becomes one DICOM General ECG Waveform Storage object named after the
input's stem. Objects are de-identified unless ``--keep-identity`` is given.
"""
import argparse
import os
import sys
from pathlib import Path

from . import codes
from .adapters.dispatch import parse, sniff
from .writer import build

_EXT = ('.xml', '.hea')


def _inputs(paths, recursive):
    for p in paths:
        p = Path(p)
        if p.is_dir():
            it = p.rglob('*') if recursive else p.glob('*')
            for f in sorted(it):
                if f.is_file() and f.suffix.lower() in _EXT:
                    yield f
        else:
            yield p


def main(argv=None):
    ap = argparse.ArgumentParser(prog='ecg2dcm-convert', description=__doc__.split('\n\n')[0])
    ap.add_argument('paths', nargs='+', help='files or directories')
    ap.add_argument('-o', '--out', default='ecg_dcm', help='output directory')
    ap.add_argument('-r', '--recursive', action='store_true')
    ap.add_argument('--uid-root', dest='uid_root', default=codes.DEFAULT_UID_ROOT)
    ap.add_argument('--keep-identity', dest='keep_identity', action='store_true')
    ap.add_argument('--start-index', type=int, default=1, help='first Instance Number / surrogate ID')
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    n_ok = n_fail = 0
    for i, f in enumerate(_inputs(a.paths, a.recursive), start=a.start_index):
        try:
            name, _ = sniff(f)
            rec = parse(f)
            ds = build(rec, index=i, deidentify_record=not a.keep_identity, uid_root=a.uid_root)
            out = Path(a.out) / (f.stem + '.dcm')
            ds.save_as(str(out), write_like_original=False)
            n_ok += 1
            print(f'{f} [{name}] -> {out}')
        except Exception as e:
            n_fail += 1
            print(f'{f}: refused: {e}', file=sys.stderr)
    print(f'{n_ok} converted, {n_fail} refused')
    return 0 if n_fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())

"""``ecg2dcm``: batch-convert a directory of GE MUSE XML exports to DICOM.

This is the command the manuscript describes. It walks a directory of MUSE XML
files, names each output from a regular expression applied to the input file
name, de-identifies every object (see docs/deidentification.md) with one
surrogate patient ID per source patient, and writes the surrogate table next
to the output so that a study can link records back under its own governance.
"""
import argparse
import os
import re
import string
import sys
import traceback
from pathlib import Path

from tqdm import tqdm

from . import codes
from .adapters import muse
from .utils import get_all_files_recursive, save_mrn_map_table, set_dcm_save_path
from .writer import build


def extract_format_keys(format_string):
    return [f for _, f, _, _ in string.Formatter().parse(format_string) if f]


def convert_one(xml_path, out_path, index, surrogates, keep_identity=False, uid_root=codes.DEFAULT_UID_ROOT):
    """Convert one MUSE file. Returns (source patient ID, surrogate ID) or raises."""
    rec = muse.parse(xml_path)
    source_id = rec.patient_id or ''
    surrogate = surrogates.get(source_id)
    if surrogate is None:
        surrogate = f'{len(surrogates) + 1:06d}'
        surrogates[source_id] = surrogate
    ds = build(rec, index=index, deidentify_record=not keep_identity,
               patient_id=None if keep_identity else surrogate, uid_root=uid_root)
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    ds.save_as(out_path, write_like_original=False)
    return source_id, surrogate


def run_conversion(args):
    if isinstance(args, dict):
        args = argparse.Namespace(**args)
    project_root = Path(args.project_root)
    root_xml_path = Path(args.data_root) / args.ecg_xml_dir
    out_root = project_root / args.output_dir
    files = get_all_files_recursive(root_xml_path, 'xml')
    if args.debug:
        files = files[:args.debug_n]

    keys = extract_format_keys(args.out_filename_pattern)
    date_keys = [k for k in keys if 'date' in k]
    assert len(date_keys) == 1, f'Expected one date key in the output filename pattern, found {len(date_keys)}.'
    date_key = date_keys[0]
    if 'seq' not in keys:
        print('Warning: no {seq} in the output filename pattern; "_{seq}" is appended so that files sharing a date stay distinct.')
        args.out_filename_pattern += '_{seq}'

    surrogates, seq_by_date, metadata = {}, {}, {}
    n_ok = n_fail = 0
    for i, xml in enumerate(tqdm(files), start=1):
        m = re.search(args.filename_pattern, xml)
        if m is None:
            print(f'skip {xml}: file name does not match --filename_pattern', file=sys.stderr)
            n_fail += 1
            continue
        g = m.groupdict()
        date = g[date_key]
        seq_by_date[date] = seq_by_date.get(date, 0) + 1
        save_dir = os.path.join(out_root, Path(xml).relative_to(root_xml_path).parent)
        out_path = set_dcm_save_path(xml, save_dir, args.out_filename_pattern,
                                     {date_key: date, 'seq': seq_by_date[date]})
        if os.path.exists(out_path):
            print(f'File {out_path} already exists. Skipping {xml}')
            continue
        try:
            source_id, surrogate = convert_one(xml, out_path, i, surrogates,
                                               keep_identity=args.keep_identity, uid_root=args.uid_root)
        except Exception as e:
            n_fail += 1
            print(f'Error processing file {xml}: {e}', file=sys.stderr)
            if args.debug:
                traceback.print_exc()
            continue
        n_ok += 1
        metadata[Path(xml).name] = {'mrn': surrogate, 'original_mrn': source_id,
                                    'ecg_dicom_file': Path(out_path).name}
    if not args.keep_identity:
        os.makedirs(out_root, exist_ok=True)
        save_mrn_map_table(metadata, str(out_root))
    print(f'{n_ok} converted, {n_fail} refused or failed')
    return n_ok, n_fail


def build_parser():
    p = argparse.ArgumentParser(prog='ecg2dcm', description='Convert GE MUSE XML ECG exports to DICOM General ECG Waveform Storage')
    p.add_argument('--debug', type=lambda s: s.lower() in ('1', 'true', 'yes'), default=False, help='process only --debug_n files and print tracebacks')
    p.add_argument('--debug_n', type=int, default=5)
    p.add_argument('--project_root', type=str, required=True, help='root directory under which --output_dir is created')
    p.add_argument('--data_root', type=str, required=True, help='root directory of the data')
    p.add_argument('--ecg_xml_dir', type=str, required=True, help='directory (under --data_root) holding the XML files')
    p.add_argument('--output_dir', type=str, default='ecg_dcm', help='output directory (under --project_root)')
    p.add_argument('--filename_pattern', type=str, required=True,
                   help=r'regex with named groups applied to each input file name, e.g. MUSE_(?P<examination_date>\d{8})_(?P<examination_time>\d{6})_(?P<seq>\d{5})')
    p.add_argument('--out_filename_pattern', type=str, required=True,
                   help='output name built from the named groups plus {seq}, e.g. ECG_DICOM_{examination_date}_{seq}')
    p.add_argument('--uid-root', dest='uid_root', default=codes.DEFAULT_UID_ROOT,
                   help='OID under which Study, Series and SOP Instance UIDs are issued (default: pydicom root, a placeholder)')
    p.add_argument('--keep-identity', dest='keep_identity', action='store_true',
                   help='do not de-identify (writes names, IDs, full timestamps and diagnosis text from the source)')
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    run_conversion(args)


if __name__ == '__main__':
    main()

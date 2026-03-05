#!/usr/bin/env python3
"""Validate JSON event files against the `schemas/ncl.iphone.v1` catalog.

Usage:
  python tools/validate_events.py [--event-dirs DIR [DIR ...]]

Defaults:
  - validates files in `schemas/ncl.iphone.v1/examples/` and `shortcuts_pack/v1/events/` (if present)

Exit codes:
  0 = all valid
  1 = one or more invalid files
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import pathlib
import sys
from jsonschema import Draft7Validator
from referencing import Registry, Resource

SCHEMA_DIR = os.path.join('schemas','ncl.iphone.v1')
INDEX_PATH = os.path.join(SCHEMA_DIR,'index.json')
ENVELOPE_PATH = os.path.join(SCHEMA_DIR,'envelope.json')


def load_catalog():
    with open(INDEX_PATH, 'r', encoding='utf-8') as fh:
        return json.load(fh)['schemas']


def load_schema_for_event_type(event_type: str, catalog: dict):
    rel = catalog.get(event_type)
    if not rel:
        return None
    path = os.path.join(SCHEMA_DIR, rel)
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh), path


def validate_instance(instance: dict, schema: dict, schema_path: str, envelope_schema: dict):
    base_uri = pathlib.Path(os.path.abspath(schema_path)).as_uri()
    registry = Registry()
    registry = registry.with_resources([
        (envelope_schema.get('$id'), Resource.from_contents(envelope_schema)),
        (pathlib.Path(os.path.abspath(ENVELOPE_PATH)).as_uri(), Resource.from_contents(envelope_schema))
    ])
    validator = Draft7Validator(schema, registry=registry)
    errs = list(validator.iter_errors(instance))
    return errs


def find_json_files(dirs: list[str]):
    files = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        files.extend(glob.glob(os.path.join(d, '*.json')))
    return sorted(files)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--event-dirs', nargs='*', default=['schemas/ncl.iphone.v1/examples', 'shortcuts_pack/v1/events'], help='Directories containing JSON event files')
    args = p.parse_args(argv)

    catalog = load_catalog()
    with open(ENVELOPE_PATH, 'r', encoding='utf-8') as fh:
        envelope_schema = json.load(fh)

    files = find_json_files(args.event_dirs)
    if not files:
        print('No event JSON files found in:', args.event_dirs)
        return 0

    total_errs = 0
    for f in files:
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
        except Exception as e:
            print(f'ERROR: could not parse {f}:', e)
            total_errs += 1
            continue

        # support either single object or list of objects per file
        instances = data if isinstance(data, list) else [data]
        for inst in instances:
            et = inst.get('event_type')
            if not et:
                print(f'INVALID ({f}): missing event_type')
                total_errs += 1
                continue
            schema_res = load_schema_for_event_type(et, catalog)
            if schema_res is None:
                print(f'INVALID ({f}): no schema for event_type {et}')
                total_errs += 1
                continue
            schema, schema_path = schema_res
            errs = validate_instance(inst, schema, schema_path, envelope_schema)
            if errs:
                print(f'INVALID ({f}) — {len(errs)} error(s) against schema {et}:')
                for e in errs:
                    path = ''.join([f'/{p}' for p in e.path])
                    print('  -', e.message, '@', path)
                total_errs += len(errs)

    if total_errs:
        print(f'Validation completed: {total_errs} error(s) found')
        return 1
    else:
        print('Validation completed: all files valid')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Build a hash-addressed manifest for a neural Docker verification run.

The manifest never stores credentials. It records the evidence files and their
SHA-256 hashes so a run can be checked later without trusting file names alone.
"""
import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tarfile


SCHEMA = 'flycoder.neural-docker-evidence.v1'


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def collect_files(path, archive_name):
    path = Path(path)
    if path.is_file():
        return [(path, archive_name)]
    if path.is_dir():
        return [(child, f'{archive_name}/{child.relative_to(path).as_posix()}')
                for child in sorted(path.rglob('*')) if child.is_file()]
    raise FileNotFoundError(f'No such file or directory: {path}')


def duplicate_archive_names(entries):
    seen = {}
    for _, archive_name in entries:
        if archive_name in seen:
            raise ValueError(f'Duplicate evidence archive path: {archive_name}')
        seen[archive_name] = True


def github_metadata():
    return {
        'repository': os.environ.get('GITHUB_REPOSITORY'),
        'commit': os.environ.get('GITHUB_SHA'),
        'workflow_run_id': os.environ.get('GITHUB_RUN_ID'),
        'workflow_run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
        'workflow_ref': os.environ.get('GITHUB_REF'),
    }


def write_manifest(args, entries):
    check = json.loads(Path(args.check_report).read_text())
    if check.get('backend_verified') is not True:
        raise ValueError('The check report does not verify the neural backend')
    if args.require_done and (check.get('task_solved') is not True or
                              check.get('outcome') != 'task_solved'):
        raise ValueError('--require-done requires a successfully solved task')
    accepted_outcomes = {item.strip() for item in args.accepted_outcomes.split(',') if item.strip()}
    if not accepted_outcomes:
        raise ValueError('At least one accepted outcome is required')
    if check.get('outcome') not in accepted_outcomes:
        raise ValueError('Outcome is not accepted: ' + str(check.get('outcome')))

    records = []
    for source, archive_name in entries:
        source_stat = source.stat()
        if stat.S_ISLNK(source_stat.st_mode):
            raise ValueError(f'Evidence file is a symlink: {source}')
        records.append({
            'path': archive_name,
            'size_bytes': source_stat.st_size,
            'sha256': sha256_file(source),
        })

    metadata = github_metadata()
    if args.commit:
        metadata['commit'] = args.commit
    metadata = {key: value for key, value in metadata.items() if value is not None}
    manifest = {
        'schema': SCHEMA,
        'created_utc': args.created_utc,
        'require_done': args.require_done,
        'accepted_outcomes': sorted(accepted_outcomes),
        'check': check,
        'source': metadata,
        'files': records,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def write_archive(archive_path, entries, manifest_path):
    archive_path = Path(archive_path)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with archive_path.open('wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as archive:
                for source, archive_name in sorted(entries, key=lambda item: item[1]):
                    info = archive.gettarinfo(str(source), arcname=f'neural-docker-evidence/{archive_name}')
                    info.uid = info.gid = 0
                    info.uname = info.gname = ''
                    info.mtime = 0
                    info.mode = stat.S_IMODE(source.stat().st_mode)
                    with source.open('rb') as handle:
                        archive.addfile(info, handle)
                manifest_info = archive.gettarinfo(str(manifest_path), arcname='neural-docker-evidence/manifest.json')
                manifest_info.uid = manifest_info.gid = 0
                manifest_info.uname = manifest_info.gname = ''
                manifest_info.mtime = 0
                manifest_info.mode = 0o644
                with manifest_path.open('rb') as handle:
                    archive.addfile(manifest_info, handle)
    return archive_path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True,
                        help='Directory containing summary.json, events.jsonl, and other run records')
    parser.add_argument('--check-report', type=Path, required=True)
    parser.add_argument('--compose-config', type=Path)
    parser.add_argument('--container-config', type=Path)
    parser.add_argument('--image-config', type=Path)
    parser.add_argument('--build-log', type=Path)
    parser.add_argument('--demo-log', type=Path)
    parser.add_argument('--commit')
    parser.add_argument('--created-utc', default=None,
                        help='Override the manifest timestamp for byte-reproducible tests')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--archive', type=Path, help='Write a deterministic .tar.gz evidence bundle')
    parser.add_argument('--require-done', action='store_true')
    parser.add_argument('--accepted-outcomes', default='task_solved',
                        help='Comma-separated checker outcomes that may be packaged')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.created_utc is None:
        args.created_utc = dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z')
    labels = {
        'check-report': (args.check_report, 'check-report.json'),
        'compose-config': (args.compose_config, 'container/compose-config.yaml'),
        'container-config': (args.container_config, 'container/container.json'),
        'image-config': (args.image_config, 'container/image.json'),
        'build-log': (args.build_log, 'container/build.log'),
        'demo-log': (args.demo_log, 'container/demo.log'),
    }
    try:
        entries = collect_files(args.run_dir, 'run')
        for path, archive_name in labels.values():
            if path is not None:
                entries.extend(collect_files(path, archive_name))
        duplicate_archive_names(entries)
        manifest = write_manifest(args, entries)
        if args.archive:
            archive_path = write_archive(args.archive, entries, args.output)
            print(json.dumps({'manifest': str(args.output), 'archive': str(archive_path),
                              'files': len(manifest['files'])}))
        else:
            print(json.dumps({'manifest': str(args.output), 'files': len(manifest['files'])}))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f'neural docker evidence packaging failed: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

"""Full, real-engine scale build through the portable executable (no fake adapters)."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
import psutil

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.make_fixtures import generate
from nordrag.util import read_json, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--count', type=int, default=30)
    parser.add_argument('--extra-pages', type=int, default=0)
    args = parser.parse_args()
    folder = ROOT / 'artifacts' / f'scale-real-{args.count}-{args.extra_pages}'
    output = folder / 'scale.ragkb'
    if output.exists():
        raise SystemExit('Existing benchmark preserved; choose a different scale')
    generate(folder / 'pptx', args.count, args.extra_pages)
    env = os.environ.copy()
    env.update(PATH=str(Path(os.environ['WINDIR']) / 'System32'), PYTHONHOME='', PYTHONPATH='', NORDRAG_DATA=str(folder / 'app-data'))
    started = time.perf_counter()
    peak = 0
    with (folder / 'build.log').open('wb') as log:
        process = subprocess.Popen([str(ROOT / 'dist/NordRAG/kb-builder.exe'), 'build', '--input', str(folder / 'pptx'), '--name', f'Scale {args.count}', '--output', str(output), '--yes'], env=env, cwd=ROOT / 'dist/NordRAG', stdout=log, stderr=subprocess.STDOUT)
        try:
            while process.poll() is None:
                total = 0
                try:
                    parent = psutil.Process(process.pid)
                    for child in [parent] + parent.children(recursive=True):
                        try:
                            total += child.memory_info().rss
                        except psutil.Error:
                            pass
                except psutil.Error:
                    pass
                peak = max(peak, total)
                time.sleep(.5)
        except BaseException:
            process.terminate()
            process.wait(timeout=15)
            raise
    report = {'real_engines': True, 'portable_executable': True, 'developer_path_removed': True, 'clean_windows': False, 'documents': args.count, 'pages': args.count * (3 + args.extra_pages), 'image_pages': 1, 'wall_seconds': round(time.perf_counter() - started, 2), 'peak_process_tree_rss_mib': round(peak / 1024**2), 'rss_note': 'Shared mapped pages may be counted more than once', 'exit_code': process.returncode}
    if output.with_suffix('.report.json').exists():
        report['build'] = read_json(output.with_suffix('.report.json'))
    write_json(folder / 'benchmark.json', report)
    print(report, flush=True)
    return process.returncode


if __name__ == '__main__':
    raise SystemExit(main())

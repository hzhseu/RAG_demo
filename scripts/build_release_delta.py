"""Compare actual release bytes and archive added/modified files only."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent.parent
OLD = ROOT / 'dist/previous-releases/NordRAG-20261005-213208-10d4f7c9'
NEW = ROOT / 'dist/NordRAG'
OUT = ROOT / 'artifacts/release-delta-2026-10-05'
ZIP = ROOT / 'RadioMind-Windows-x64-reranking-delta-2026-10-05.zip'


def digest(stream):
    h = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        h.update(block)
    return h.hexdigest()


def inventory(root):
    result = {}
    for i, path in enumerate(sorted(root.rglob('*'))):
        if path.is_symlink():
            raise RuntimeError(f'Symlink unsupported: {path}')
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            result[path.relative_to(root).as_posix()] = {
                'sha256': digest(stream), 'bytes': path.stat().st_size}
        if len(result) % 5000 == 0:
            print(f'{root.name}: hashed {len(result)} files', flush=True)
    return result


def main():
    if ZIP.exists():
        raise SystemExit('Output already exists; preserving it')
    OUT.mkdir(parents=True, exist_ok=True)
    old, new = inventory(OLD), inventory(NEW)
    added = sorted(new.keys() - old.keys())
    deleted = sorted(old.keys() - new.keys())
    modified = sorted(k for k in old.keys() & new.keys()
                      if old[k]['sha256'] != new[k]['sha256'])
    unchanged = len(new) - len(added) - len(modified)
    report = {'baseline': str(OLD), 'latest': str(NEW),
              'comparison': 'SHA256 of actual bytes of every file',
              'added': {k: new[k] for k in added},
              'modified': {k: {'old': old[k], 'new': new[k]} for k in modified},
              'deleted': {k: old[k] for k in deleted},
              'unchanged_count': unchanged}
    manifest = OUT / 'delta-manifest.json'
    manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 发行版本逐文件差异与增量更新说明', '',
             f'旧版本：`{OLD}`', f'新版本：`{NEW}`', '',
             '比较全部实际文件的 SHA256，忽略修改时间；不依赖发行包自带的校验清单。', '',
             f'新增 {len(added)}；修改 {len(modified)}；删除 {len(deleted)}；内容相同 {unchanged}。', '',
             '## 更新方法', '',
             '1. 退出程序及相关模型进程，备份目标机现有程序目录和用户数据。',
             '2. 本包仅适用于上述旧版本。把压缩包中的 `NordRAG` 目录内容覆盖到旧版本程序根目录（不要多嵌套一层目录）。',
             '3. 如目标环境自行修改了 `runtime.json` 等配置，先备份并合并配置；覆盖将使用新发行版配置。保留目标机自己的知识库和会话数据。',
             '4. 如需程序目录与新版完全一致，按下方“删除”清单移走旧文件；压缩包覆盖不会自动删除这些文件。清单外的用户自建文件不要删除。',
             '5. 启动前运行 `kb-builder.exe doctor`，再打开 `nord-chat.exe` 检查检索重排开关。', '',
             '包内 `delta-manifest.json` 记录旧、新 SHA256 与大小，可检查基线及更新结果。增量包按整文件分发，不是二进制差分。', '']
    for title, names in [('新增', added), ('修改', modified), ('删除', deleted)]:
        lines += [f'## {title}（{len(names)}）', '']
        lines += [f'- `{name}`' for name in names] or ['无。']
        lines += ['']
    readme = OUT / 'DELTA-README.md'
    readme.write_text('\n'.join(lines), encoding='utf-8')
    selected = added + modified
    print(json.dumps({'added': len(added), 'modified': len(modified), 'deleted': len(deleted), 'unchanged': unchanged, 'payload_bytes': sum(new[k]['bytes'] for k in selected)}), flush=True)
    partial = ZIP.with_suffix('.zip.partial')
    if partial.exists():
        raise SystemExit('Partial output already exists; preserving it')
    with zipfile.ZipFile(partial, 'w', zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
        for name in selected:
            archive.write(NEW / name, 'NordRAG/' + name)
        archive.write(manifest, manifest.name)
        archive.write(readme, readme.name)
    print('Verifying delta payload and reconstructed release inventory...', flush=True)
    reconstructed = dict(old)
    with zipfile.ZipFile(partial) as archive:
        assert len(archive.namelist()) == len(selected) + 2
        for name in selected:
            with archive.open('NordRAG/' + name) as stream:
                actual = digest(stream)
            assert actual == new[name]['sha256'], name
            reconstructed[name] = new[name]
        assert archive.read(manifest.name) == manifest.read_bytes()
        assert archive.read(readme.name) == readme.read_bytes()
    for name in deleted:
        del reconstructed[name]
    assert reconstructed == new
    partial.rename(ZIP)
    with ZIP.open('rb') as stream:
        checksum = digest(stream)
    ZIP.with_suffix('.zip.sha256.txt').write_text(f'{checksum}  {ZIP.name}\n', encoding='ascii')
    print(json.dumps({'archive': str(ZIP), 'bytes': ZIP.stat().st_size, 'sha256': checksum, 'verified_payload_files': len(selected), 'reconstructed_inventory_matches': True}), flush=True)


if __name__ == '__main__':
    main()

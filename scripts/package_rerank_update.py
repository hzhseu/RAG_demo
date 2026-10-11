"""Build the model-free incremental update from a verified Windows folder."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parent.parent
FILES = ('nord-chat.exe', '_internal/base_library.zip', 'docs/RERANKING.md')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    release = ROOT / 'dist/NordRAG'
    output = ROOT / 'dist/RadioMind-Rerank-Incremental-20261010'
    output.mkdir(exist_ok=True)
    cfg = json.loads((release / 'runtime.json').read_text(encoding='utf-8-sig'))
    assert cfg['reranker_candidates'] == 16 and cfg['reranker_top_k'] == 8
    checksums = json.loads((release / 'checksums.json').read_text(encoding='utf-8'))
    manifest = {'format': 1, 'description': '16 candidates and request-local scoring reuse; non-Intel UI release',
                'files': {}, 'dependencies': {}}
    for name in FILES:
        source = release / name
        assert sha(source) == checksums[name], name
        target = output / 'payload' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        manifest['files'][name] = sha(source)
    for path in sorted((release / '_internal').rglob('*')):
        if path.is_file() and path.relative_to(release).as_posix() not in FILES:
            manifest['dependencies'][path.relative_to(release).as_posix()] = sha(path)
    (output / 'update-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    for name in ('Apply-Update.ps1', 'Apply-Update.cmd'):
        text = (ROOT / 'scripts/rerank_incremental' / name).read_text(encoding='utf-8-sig')
        (output / name).write_text(text, encoding='utf-8-sig' if name.endswith('.ps1') else 'ascii', newline='\r\n')
    (output / 'README-增量更新.txt').write_text('''RadioMind 重排增量更新（2026-10-10）

适用：此前提供的、没有“启用 Intel 硬件加速”复选框、已支持检索重排的 Windows 离线版本。
更新内容：候选数 30 -> 16，最终仍保留 8 条；复用同轮问题分词与相同评分输入。

使用步骤：
1. 关闭主程序和建库工具。
2. 将本压缩包内的所有内容解压到旧程序目录（与 nord-chat.exe、runtime.json 同级）。
3. 双击 Apply-Update.cmd。看到 SUCCESS 后再启动 nord-chat.exe。
仅解压还不会完成更新：必须运行 Apply-Update.cmd，它会自动备份并覆盖程序、调整配置。
也可以把旧程序文件夹拖到 Apply-Update.cmd 上。

更新器只替换 nord-chat.exe、_internal/base_library.zip、docs/RERANKING.md，
并把原 runtime.json 的 reranker_candidates 改为 16、更新相应校验值。
模型路径、其他参数、模型目录、知识库、聊天记录、模型选择保持原样；无需重建知识库。
不包含模型，不需要联网、Python 或重新安装依赖。

更新前自动核对依赖版本和文件哈希。若提示版本不兼容或程序仍在运行，
请不要手动强制覆盖 payload；保留提示信息供排查。
备份在旧程序目录的 update-backups/rerank-时间-编号/files 下。
如需回退，关闭程序，把该 files 文件夹内的内容复制回旧程序目录并覆盖。
更新失败时会自动尝试恢复；若恢复失败，界面会列出需手动恢复的文件。

16 个不同短片段的接口调用从 48 次降为 33 次。
开发机三轮样本耗时中位数约 6.90 -> 6.71 秒，评分一致；155U 的实际提升需实测。
''', encoding='utf-8-sig')
    archive = output.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(output.rglob('*')):
            if path.is_file():
                z.write(path, path.relative_to(output).as_posix())
    archive.with_suffix('.zip.sha256.txt').write_text(f'{sha(archive)}  {archive.name}\n', encoding='ascii')
    print(f'{archive}\n{archive.stat().st_size / 1024**2:.2f} MiB; {len(manifest["dependencies"])} dependency hashes')


if __name__ == '__main__':
    main()

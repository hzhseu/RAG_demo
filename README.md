# RadioMind · 离线 PPT 知识库

独立测试回答模型：双击 `Start-model-test.cmd` 或 `dist/ModelTester/ModelTester.exe`，可进行持续对话、材料问答和摘要追问，无需知识库。复用已有模型文件，支持可配置的模型选择、会话切换、耗时显示、停止生成和导出完整对话。详情见 [独立模型测试说明](docs/MODEL_TESTER.md)。

Windows 本地 RAG Demo。知识库通过独立工具构建，浏览器用于对话、资料浏览、引用原页预览和标签整理。

## 交付包使用

1. 将完整 `dist/NordRAG` 文件夹复制到可写目录。不要只复制 exe。
   首次体验可直接双击 `Try-demo.cmd`，使用随包附带的测试 PPTX 知识库。
2. 双击 `kb-builder.exe`，输入 PPTX 目录、知识库名称和输出路径，确认清单后构建。
3. 双击 `nord-chat.exe`，选择生成的 `.ragkb`，浏览器自动打开。
4. 保留启动窗口。按 Ctrl+C 退出并停止本地模型。重新选择知识库可运行 `nord-chat.exe --choose`。

命令行构建：

```powershell
./kb-builder.exe build --input 'D:\资料' --name '部门知识库' --output 'D:\知识库\部门.ragkb'
./kb-builder.exe build --input 'D:\资料' --name '部门知识库' --output 'D:\知识库\部门新版.ragkb' --exclude '子目录/损坏文件.pptx' --yes
./kb-builder.exe doctor
```

文档变化后重新构建，不支持版本回退。标签在本地保存，点击“导出知识库”可将修改随包迁移。`.ragkb` 包含原始 PPTX 和解析内容，不是加密文件。

当前版本构建失败时，终端会列出失败文件、处理阶段、异常类型和原因，并显示本次 `.report.json` 的完整路径。该报告位于输出 `.ragkb` 旁边；例如 `部门.ragkb` 对应 `部门.report.json`。超时会显示中文提示，可先关闭其他高负载任务再重试；成功处理的缓存会被复用。若提示“输出已存在”，请换一个新的输出文件名。报告无法保存时仍会在终端显示原始错误，不会把旧报告当作本次结果。

构建时生成总结或分类遇到模型连接／读取超时，会自动停止本次启动的聊天模型，缩小总结输入批次后重试一次（最多两次尝试）。终端会显示“自动恢复”和总结片段进度。交互问答不会自动重放已经输出的回答。

当前版本默认自动跳过失败文件：扫描、解析／OCR、预览转换、总结、分类或向量生成失败时，会记录具体文件、阶段和原因，继续用成功文档构建。部分成功会显示“构建完成，部分文件已跳过”、成功／跳过数量和报告路径，命令退出码为 0；报告状态为 `complete_with_warnings`（全部成功为 `complete`）。请检查报告中的 `failed` 列表，确认缺失的资料；知识库只包含成功文档，页数、片段和引用也仅计算成功内容。

自动跳过不会删除或修改原 PPTX，也不会永久排除文件。修复文件或运行环境后，使用新的输出文件名重新构建，程序会重新尝试这些文件，并复用有效的解析和总结缓存。`--exclude` 仍可用于主动排除指定文件。所有文档失败或没有可用文档时不生成知识库，退出码为 1。用户取消、公共模型启动失败、缓存／输出写入失败、索引和打包校验失败会终止构建，不会作为单个坏文件忽略。本次更新只涉及源码；旧版 `kb-builder.exe` 需要重新打包才会具有此行为。

交付文件夹约 5.4 GiB，含模型、OCR、转换程序、字体和测试知识库。使用说明与组件清单见 `docs/DELIVERY.md`，测试结果及待验证边界见 `docs/TEST_REPORT.md`，独立测试入口见 `docs/MODULE_TESTS.md`。真实界面截图位于 `docs/interface-preview.png`。

## 迁移到另一台 Windows

将 `RadioMind-Windows-x64-2026-10-03.zip` 复制到 Windows 10/11 x64 电脑，完整解压至可写目录；不要在压缩包内直接运行，也不要只复制 EXE。预留至少 12 GiB 用于压缩包和解压后的程序，知识库、缓存及工作副本另需空间。

目标机无需安装 Python、Node.js 或 Office，也无需下载模型；需有可用的现代 Edge 或 Chrome 浏览器。双击 `Try-demo.cmd` 可先测试，正式使用双击 `nord-chat.exe`，在页面顶部选择知识库；从 PPTX 生成新库则运行 `kb-builder.exe`。

自己的 `.ragkb` 文件需另外复制。若修改过分类标签，先在原电脑“导出知识库”，再迁移导出的文件。聊天记录、最近打开路径和构建缓存不自动随程序迁移；若确需保留历史，可在两端程序都关闭后另外复制 `%LOCALAPPDATA%/NordRAG`，然后重新选择目标机上的知识库路径。

可运行 `kb-builder.exe doctor` 检查离线组件完整性。压缩包旁的 `.sha256.txt` 是传输校验值，解压目录中的 `checksums.json` 是文件清单。首次启动会校验模型与组件，请等待启动窗口显示本地网址。

## 在界面选择知识库（当前版本）

启动 `./.venv/Scripts/python.exe -m nordrag.launcher` 后，点击页面顶部“选择知识库”，再点击“打开本机文件”，在 Windows 文件窗口选择 `.ragkb` 文件。最近使用列表最多保留 10 个知识库，可直接点击切换，无需重启。文件始终在本机读取。

首次使用或上次文件已移动时，软件仍会打开页面，提示选择知识库。正常启动会恢复上次打开的文件；加 `--choose` 可跳过恢复，直接进入未选库界面；`--knowledge 路径` 可指定启动时加载的文件。

生成回答、专题总结或导出期间不能切换。取消选择、文件损坏或模型不兼容不会替换当前知识库。对话与标签按知识库版本保留；本地标签不会自动写回原 `.ragkb`，需要分享时仍使用“导出知识库”。其他已打开页面会自动同步所选知识库。

请从启动程序自动打开的页面进入。出现“会话令牌无效”时，重新使用启动窗口给出的完整链接；选择知识库功能不会绕过访问验证。2026-10-03 重新打包的 EXE 已包含本功能。

``## 本地开发

`powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.lock.txt
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
./.venv/Scripts/python.exe -m pytest
node --test --test-isolation=none frontend/tests/apiClient.test.mjs
./.venv/Scripts/python.exe scripts/make_fixtures.py
./.venv/Scripts/python.exe -m nordrag.cli scan artifacts/fixtures/pptx
```

`runtime.json` 的所有相对路径都相对于配置文件。可用 `--config` 指定配置（构建工具放在子命令之前）。复制 `runtime.example.json` 后准备组件，运行 `scripts/freeze_runtime.py` 固定实际模型哈希和组件清单。

```powershell
./.venv/Scripts/python.exe scripts/provision.py
./.venv/Scripts/python.exe scripts/freeze_runtime.py
./.venv/Scripts/python.exe -m nordrag.cli doctor
./.venv/Scripts/python.exe -m nordrag.cli build --input artifacts/fixtures/pptx --name '测试知识库' --output artifacts/test.ragkb --yes
./.venv/Scripts/python.exe -m nordrag.launcher --knowledge artifacts/test.ragkb
./.venv/Scripts/python.exe scripts/acceptance.py artifacts/test.ragkb
./.venv/Scripts/python.exe scripts/package_windows.py
```

下载脚本仅供开发准备；正式程序不联网获取模型。OCR 使用独立的 Windows Python + PaddleOCR 运行目录，LibreOffice 使用解包后的本地转换组件。完整准备步骤与验收边界见 `docs/DELIVERY.md`。

重新打包前，脚本会将整个旧 `dist/NordRAG` 保存到 `dist/previous-releases/NordRAG-时间戳-标识`，构建失败也保留备份。旧包中的 `.ragkb` 会复制回新包；遇到同名不同内容时，旧知识库保存在新包的 `preserved-knowledge` 下。建议日常知识库存放在独立的 `knowledge_bases` 或其他资料目录；迁移时同时携带需要的知识库文件。

## 项目结构与独立测试

- `nordrag/parsing.py`：扫描、去重、解析和页级分块。
- `nordrag/package.py`：校验、加载和导出 `.ragkb`。
- `nordrag/index.py`：SQLite FTS5 中英文关键词和向量混合检索。
- `nordrag/engines.py`、`ocr_worker.py`：真实 llama.cpp、OCR 和 LibreOffice 适配器。
- `nordrag/builder.py`：缓存、失败报告和原子发布。
- `nordrag/generation.py`：证据预算、引用检查、摘要。
- `nordrag/api.py`：本机服务、会话、取消、标签与导出。
- `frontend`：React/TypeScript 北欧风格界面，本地 PDF.js。
- `tests`：独立测试；外部引擎替身仅用于测试，不代表实际模型质量。

默认数据目录 `%LOCALAPPDATA%/NordRAG`，可通过 `NORDRAG_DATA` 指向其他可写目录。下分 `cache`、`work`、`labels`、`sessions`、`exports`、`logs`。日志轮转限制大小，只记录固定事件名、计数和异常类型，不记录提示词、原文或回答。清理缓存不删除源文件或历史会话；会话可以在界面单独删除。启动时会校验完整组件，首次打开请等待控制台出现本地网址。

## 已知产品边界

- 面向文字、原生表格和图片中的文字；不承诺理解复杂图形关系、动画或曲线趋势。
- OCR 可能误识别数字；重要回答需核对原页。引用编号有效不等于事实被证据支持，必须单独评估回答忠实度。
- LibreOffice 预览可能因字体和复杂排版与 PowerPoint 不同。
- CPU 延迟依硬件、页数、图片比例而变；开发机通过不等于干净目标机已验收。
- 同时只执行一个构建/生成任务。网络服务绑定 127.0.0.1，同源和随机会话令牌保护本地接口。

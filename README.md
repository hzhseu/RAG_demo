# Nord · 离线 PPT 知识库

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

交付文件夹约 5.4 GiB，含模型、OCR、转换程序、字体和测试知识库。使用说明与组件清单见 `docs/DELIVERY.md`，测试结果及待验证边界见 `docs/TEST_REPORT.md`，独立测试入口见 `docs/MODULE_TESTS.md`。真实界面截图位于 `docs/interface-preview.png`。

## 本地开发

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.lock.txt
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
./.venv/Scripts/python.exe -m pytest
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

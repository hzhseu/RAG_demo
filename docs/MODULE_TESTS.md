# 独立测试入口

在项目根目录执行下列开发命令。单元测试中的外部引擎替身只隔离依赖，不能替代真实模型测试。

| 功能 | 独立入口 |
|---|---|
| PPTX 扫描与清单 | `kb-builder.exe scan "D:\资料"` |
| 运行组件与模型完整性 | `kb-builder.exe doctor` |
| 解析、表格、备注、分块、关键词/向量索引、知识库包 | `.venv/Scripts/python.exe -m pytest tests/test_core.py` |
| 构建缓存、失败、排除和取消 | `.venv/Scripts/python.exe -m pytest tests/test_build.py` |
| 证据预算、引用与专题综合 | `.venv/Scripts/python.exe -m pytest tests/test_generation.py` |
| API、会话、标签、导出及生成取消 | `.venv/Scripts/python.exe -m pytest tests/test_api.py` |
| Windows 子进程、锁、工作副本及配置校验 | `.venv/Scripts/python.exe -m pytest tests/test_processes.py tests/test_safety.py tests/test_workspace.py tests/test_config.py` |
| 真实嵌入与检索 Recall@8 | `.venv/Scripts/python.exe scripts/acceptance.py artifacts/delivery-demo.ragkb` |
| 真实生成及性能记录 | `.venv/Scripts/python.exe -X utf8 scripts/real_smoke.py artifacts/delivery-demo.ragkb` |
| 打包 EXE 完整构建 | `.venv/Scripts/python.exe scripts/packaged_build_check.py` |
| 真实规模构建、耗时及内存 | `.venv/Scripts/python.exe scripts/scale_benchmark.py --count 30 --extra-pages 0` |

OCR 独立工作进程接受四个参数：输入图片、输出 JSON、检测模型目录、识别模型目录：

```powershell
./runtime/ocr/python.exe ./nordrag/ocr_worker.py ./artifacts/fixtures/ocr-fixture.png ./artifacts/ocr-output.json ./runtime/ocr-models/PP-OCRv5_mobile_det_infer ./runtime/ocr-models/PP-OCRv5_mobile_rec_infer
```

转换与模型适配器分别由 `Engines.convert(source, target, expected_pages)`、`Engines.embed(texts, query=False)`、`Engines.stream(messages, cancel_event)` 提供。转换会校验输出 PDF 页数；OCR 和转换运行于独立子进程；模型进程仅监听本机并使用随机访问令牌。

浏览器自动化分两层：`ui_check.cjs` 使用测试服务隔离界面；`packaged_smoke.py` 启动真实 EXE，`packaged_ui_check.cjs` 检查真实回答与 PDF 像素绘制。运行脚本前需安装 Playwright 并提供 Edge；这些仅为开发验收依赖，目标机使用已有浏览器。

验收脚本不覆盖已有知识库。重复测试时选择新的输出路径或保留旧报告后显式删除该次测试产物。

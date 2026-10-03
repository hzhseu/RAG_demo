# 离线交付与验收

## 完整组件

`runtime/llama`：固定版本 Windows CPU x64 llama.cpp，含 DLL。

`runtime/models`：新增 Qwen3.5-4B Q4_K_M，保留 Qwen3-4B-Instruct-2507 Q4_K_M（社区 GGUF 转换，记录来源）与官方 Qwen3-Embedding-0.6B Q8_0。

`runtime/ocr`：Python 3.13.7 Windows embeddable 完整目录，`python313._pth` 添加 `Lib/site-packages` 并开启 `import site`。在该目录安装 PaddlePaddle 3.3.1 和 PaddleOCR 3.5.0 的全部依赖；不可仅复制开发机 venv。

`runtime/ocr-models`：PP-OCRv5_mobile_det 和 PP-OCRv5_mobile_rec 的本地推理模型。禁止用缺失模型触发在线下载。

`runtime/LibreOffice-25.8.2.2`：LibreOffice 25.8.2.2 完整行政解包内容。可在开发阶段用 `msiexec /a <离线msi> /qn TARGETDIR=<项目内绝对目录>` 解包；在首次执行前运行 `scripts/disable_lo_updates.py`，关闭组件默认自动更新。转换适配器另使用关闭更新的独立用户配置。不要求目标机安装 Office。

`runtime/runtime-lock.json`：运行文件校验清单。修改组件后重新 freeze，确保解析缓存失效。

运行 `scripts/stage_fonts.py` 将 LibreOffice 随附字体及 Noto Sans CJK SC 2.004 放入 `share/fonts/truetype`，供转换进程私有加载，不安装系统字体；同时将 Noto 复制到 `frontend/public/fonts`，供浏览器本地备用字体使用。Noto 的 SIL OFL 许可证随包保留。特殊商业字体仍可能被替代，需在目标机复核排版。Windows 私有字体路径依据 [LibreOffice 25.8.2.2 官方实现](https://github.com/LibreOffice/core/blob/libreoffice-25.8.2.2/vcl/win/gdi/salfont.cxx)。

运行 `scripts/stage_crt.py` 将微软官方 VC14 x64 Redistributable 14.51.36247.0 的最小运行库复制至各引擎程序目录。下载来源、校验值及说明随包保留；避免依赖开发机已安装的 Visual C++ 运行库。LibreOffice MSI 附带的旧版 14.29 不兼容本次 llama.cpp 构建，不能替代。完成后再执行 freeze 和打包。

运行 `scripts/package_windows.py` 生成完整包。`--app-only` 只生成开发程序，带明显标记，不是可交付的完整离线包。

## 许可证

交付必须保留各组件原有许可证。Qwen 模型：Apache-2.0；llama.cpp：MIT；PaddleOCR/PaddlePaddle：Apache-2.0；LibreOffice：MPL-2.0/LGPL 等，保留安装内容中的版权与许可证；Python：PSF；React：MIT；PDF.js：Apache-2.0；Noto 字体：SIL OFL 1.1。OCR Python 依赖的 dist-info 许可证随运行目录保留。`scripts/license_inventory.py` 收集后端和前端依赖的版本、元数据及许可证至 `docs/dependency-notices`，包含开发工具并明确标注范围。下载来源及固定版本保存至 `runtime/sources.json`，最终输出文件校验值在 `checksums.json`。

## 验收记录必须区分

1. 自动化模块/API 测试（允许外部引擎替身）。
2. 本机真实 Qwen / OCR / LibreOffice 闭环。
3. 断网、无开发环境、无 Office 的干净 Windows 验收。
4. 目标机真实文档与 20–30 个业务问题验收。

任何上一层通过都不能代替下一层。`scripts/acceptance.py` 仅验证真实嵌入模型检索，不声称证明回答忠实度。

测试规模：`scripts/make_fixtures.py --output artifacts/scale/pptx --count 40 --extra-pages 7` 生成 40 文件/400 页，页数和图片比例应在真实资料到位后进一步匹配。

记录总页数、图片页占比、构建耗时、首字延迟、生成速度、峰值内存、包体大小、引用页准确性、数字/单位准确性，以及预览缺字/错位。干净机先完全断网再启动和构建，以发现对开发机缓存的隐式依赖。

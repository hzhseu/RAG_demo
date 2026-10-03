# Qwen3.5 双模型版

主程序顶部“回答模型”可选择 Qwen3.5-4B 或原 Qwen3-4B-Instruct-2507。切换需要等待当前任务完成；成功切换自动新建会话，点击旧会话会恢复其模型。新安装默认 Qwen3.5，下次启动恢复上次成功选择。加载失败显示原因，旧会话保留。

两个程序目录保持为同级的 NordRAG 与 ModelTester。测试工具和构建工具均读取 NordRAG/chat-models.json；现有 model-test-models.json 自定义条目仍可用。模型路径相对于配置文件目录；新增条目必须固定 SHA256。原 default ID 表示 Qwen3-4B-Instruct-2507。

构建示例：`kb-builder.exe build --input PPT目录 --name 部门知识库 --output 新知识库.ragkb --model qwen35-4b --yes`；使用旧模型传 `--model default`。双击构建工具会列出模型选择。

旧知识库无需重建向量索引，嵌入模型、池化和查询前缀未改变。旧文档摘要及分类保持原结果；需要更新时选择模型重新构建。生成缓存按模型及参数隔离，可证明兼容的解析缓存跨模型复用；旧缓存不删除。

Qwen3.5 使用 Q4_K_M，CPU 4 线程、8192 上下文；通过聊天模板 enable_thinking=false 关闭思考，不使用 /nothink。生成参数温度 0.7、top_p 0.8、top_k 20、min_p 0、presence_penalty 1.5、repeat_penalty 1.0。旧模型温度仍为 0.1。

固定下载来源：Unsloth/Qwen3.5-4B-GGUF，revision e87f176479d0855a907a41277aca2f8ee7a09523，文件 Qwen3.5-4B-Q4_K_M.gguf，SHA256 00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4。模型及转换权重按 Apache-2.0 许可证分发。文本推理使用已验收的 llama.cpp b11326；不启用视觉输入。

## 回退

退出新版程序，打开 dist/previous-releases 中保留的旧 NordRAG 目录运行 nord-chat.exe。旧版完整运行组件和原知识库均保留；不要把新版 runtime.json 单独复制到旧目录。模型选择设置独立保存为用户数据目录的 model-selection.json，旧版可忽略。

原交付中的 .ragkb、自定义模型配置及其他文件完整保存在旧交付备份。新版复制知识库及兼容的自定义配置。新增模型、旧模型和嵌入模型均随完整包提供，正式运行不下载任何组件。

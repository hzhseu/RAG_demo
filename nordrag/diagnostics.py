"""Readable local diagnostics; do not send document contents to event logs."""
import subprocess
import httpx


class ComponentUnavailableError(RuntimeError):
    """A shared model could not start; skipping input files cannot fix this."""


STAGES = {
    'scan': '扫描 PPTX', 'cache': '读取或准备缓存', 'parse': '解析 PPTX / 图片 OCR',
    'convert': '转换 PDF 预览', 'copy': '整理文档文件', 'chunk': '提取检索片段',
    'organize': '生成文档总结', 'embedding': '生成检索向量', 'index': '建立检索索引',
    'seal': '打包并校验知识库', 'report': '保存构建报告',
    'summarizing': '生成文档总结', 'classify': '生成分类和标签',
}


def describe_error(error):
    message = str(error).strip()
    if isinstance(error, (TimeoutError, httpx.TimeoutException, subprocess.TimeoutExpired)):
        message = '处理超时。请检查本地模型或转换组件是否仍在运行；关闭其他高负载任务后重试。' + (f' 原始信息：{message}' if message else '')
    elif isinstance(error, KeyboardInterrupt):
        message = '用户中断了构建'
    elif not message:
        message = '组件未提供详细错误信息'
    return f'{type(error).__name__}: {message}'

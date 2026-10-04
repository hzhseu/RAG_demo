"""Recognize unqualified library totals without guessing from retrieved passages."""
import re
import unicodedata


_REQUEST = r'(?:(?:请问|请|麻烦你?|帮我|告诉我|帮忙|统计一下|统计|查询一下|查询|查看一下|查看|数一下|数一数)[,，]?)*'
_SCOPE = r'(?:(?:当前|现在|目前|这个|该|本)?(?:文档库|知识库|资料库|库)(?:里面|中|里|内)?的?)?'
_NOUN = r'(?:pptx?(?:文档|文件)?|文档|文件|项目)'
_TOTAL = r'(?:一共|总共|总计|共)?'
_VERB = r'(?:有|收录了?|包含了?|已收录|已导入|导入了?)?'
_QUANTITY = r'(?:多少|几)(?:个|份)?'
_COUNT_PATTERNS = [
    re.compile(_REQUEST + r'(?:当前|现在|目前)?' + _SCOPE + body + r'(?:呢|吗|呀|啊)?')
    for body in (
        _TOTAL + _VERB + _QUANTITY + _NOUN,
        _NOUN + r'的?(?:总数|数量|数目)(?:是|为|有)?(?:多少|几)?',
        _NOUN + _TOTAL + _VERB + _QUANTITY,
    )
]
_ENGLISH_COUNT = re.compile(
    r'(?:please tell me )?how many (?:documents|projects|files|pptx files|pptx documents)'
    r'(?: are (?:there(?: in (?:the |this |current )?(?:knowledge base|document library|library))?'
    r'|in (?:the |this |current )?(?:knowledge base|document library|library)))?'
)


def is_catalog_count_question(question):
    # Full matches are deliberate: a suffix such as "涉及无线通信" changes the scope.
    text = unicodedata.normalize('NFKC', question).strip().rstrip('?!。.！').strip().lower()
    chinese = re.sub(r'\s+', '', text)
    return any(pattern.fullmatch(chinese) for pattern in _COUNT_PATTERNS) or bool(
        _ENGLISH_COUNT.fullmatch(re.sub(r'\s+', ' ', text))
    )


def catalog_count_answer(documents, knowledge_version, question):
    total = len(documents)
    source = {
        'type': 'catalog', 'scope': 'all_documents', 'knowledge_version': knowledge_version,
        'document_count': total, 'project_count': total,
    }
    if re.search(r'[\u3400-\u9fff]', question):
        answer = (f'当前知识库共收录 {total} 份 PPTX 文档，对应 {total} 个项目。'
                  '\n来源：当前知识库完整文档目录；每份 PPTX 文档对应一个项目。')
    else:
        answer = (f'The current knowledge base contains {total} PPTX documents, representing {total} projects.'
                  '\nSource: the complete document catalog of the current knowledge base; each PPTX represents one project.')
    return answer, source

import pytest

from nordrag.catalog import is_catalog_count_question


@pytest.mark.parametrize('question', [
    '文档库中有多少文档？', '有几个项目', '知识库中有几个项目？',
    '请问当前文档库里一共有多少份PPTX文档？', '文档库中共收录了多少文档？',
    '一共有多少个项目？', '目前有多少份文档？', '总共有几个项目呢？',
    '文档总数是多少？', '当前知识库的项目数量是多少？', '请统计一下文档数量。',
    '帮我统计一下当前知识库里的文档总数', '项目有几个？', '文档库的文档有多少份？',
    '知识库共有多少个项目？', '现在收录了多少份 PPTX？',
    'How many documents are in the knowledge base?', 'How many projects are there?',
])
def test_global_count_questions_are_routed_to_catalog(question):
    assert is_catalog_count_question(question)


@pytest.mark.parametrize('question', [
    '某个文档里提到几个项目？', '这个项目有多少文档？', '有几个项目涉及无线通信？',
    '文档库中有多少文档涉及无线通信？', '涉及无线通信的项目有几个？',
    '今年有几个项目？', '当前筛选结果有多少文档？', '选中的文档有多少个？',
    '这些文档有几个项目？', '项目A里有几个子项目？', '文档库有多少页？',
    '文档库有多少文档？请总结各项目内容。', '项目数量是多少，预算是多少？',
    '请把“有几个项目”翻译成英语', '资料的主要内容是什么？',
    'How many documents mention wireless technology?', '',
])
def test_scoped_or_compound_questions_do_not_use_global_total(question):
    assert not is_catalog_count_question(question)

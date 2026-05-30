"""Debug test for JSON code block parsing"""
import json
import sys
sys.path.insert(0, 'src')

from unittest.mock import patch, MagicMock
from xueqiu_analyzer.extractor import call_deepseek_extract

# 模拟 test_json_in_code_block 的 mock 设置
mock_response = MagicMock()
mock_response.__enter__ = MagicMock(return_value=mock_response)
mock_response.__exit__ = MagicMock(return_value=False)

# 设置 raw = '```json\n{...}\n```'
raw_content = json.dumps({
    'title': '贵州茅台2024年度财报分析',
    'author': '张三',
    'content': '正文内容' * 20,
    'time': '2024-03-28 10:00',
    'symbols': ['600519'],
}, ensure_ascii=False)
raw = '```json\n' + raw_content + '\n```'

mock_response.read.return_value = json.dumps({
    'choices': [{'message': {'content': raw}}]
}).encode()

with patch('xueqiu_analyzer.extractor.urllib.request.urlopen', return_value=mock_response):
    result = call_deepseek_extract('<html>test</html>', 'https://xueqiu.com/123/456')
    print('title:', repr(result.title))
    print('OK' if result.title == '贵州茅台2024年度财报分析' else 'FAIL')
"""
Text similarity helpers.

Extracted from the (deleted) provenance_engine so that petition_writer_v3 can
keep recovering snippet ids by fuzzy text match without carrying the v1
provenance stack.
"""

import re
from difflib import SequenceMatcher
from typing import List


def text_similarity(text1: str, text2: str) -> float:
    """
    计算两段文本的相似度

    组合使用：
    1. SequenceMatcher (编辑距离)
    2. 词重叠度
    3. 数字/实体匹配
    """
    if not text1 or not text2:
        return 0.0

    text1_lower = text1.lower()
    text2_lower = text2.lower()

    # 1. SequenceMatcher 相似度
    seq_ratio = SequenceMatcher(None, text1_lower, text2_lower).ratio()

    # 2. 词重叠度
    words1 = set(_extract_words(text1_lower))
    words2 = set(_extract_words(text2_lower))

    if not words1 or not words2:
        word_overlap = 0.0
    else:
        intersection = words1 & words2
        word_overlap = len(intersection) / min(len(words1), len(words2))

    # 3. 数字匹配
    numbers1 = set(_extract_numbers(text1))
    numbers2 = set(_extract_numbers(text2))

    if numbers1 and numbers2:
        number_overlap = len(numbers1 & numbers2) / max(len(numbers1), len(numbers2))
    else:
        number_overlap = 0.0

    # 加权平均
    similarity = (
        seq_ratio * 0.3 +
        word_overlap * 0.5 +
        number_overlap * 0.2
    )

    return round(similarity, 3)


def _extract_words(text: str) -> List[str]:
    """提取有意义的词（过滤停用词）"""
    # 简单的停用词列表
    stopwords = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
        'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
        'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'this',
        'that', 'these', 'those', 'it', 'its', 'he', 'she', 'they', 'them',
        'his', 'her', 'their', 'our', 'your', 'my', 'which', 'who', 'whom',
        'whose', 'what', 'where', 'when', 'why', 'how', 'all', 'each', 'every',
        'both', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'not',
        'only', 'same', 'so', 'than', 'too', 'very', 'just', 'also'
    }

    words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    return [w for w in words if w not in stopwords]


def _extract_numbers(text: str) -> List[str]:
    """提取数字（包括带单位的）"""
    # 匹配各种数字格式
    patterns = [
        r'\$[\d,]+(?:\.\d+)?',  # $100,000.00
        r'[\d,]+(?:\.\d+)?%',   # 85.5%
        r'\d{4}',               # 年份 2024
        r'\d+(?:,\d{3})+',      # 大数字 1,000,000
        r'\d+(?:\.\d+)?'        # 普通数字
    ]

    numbers = []
    for pattern in patterns:
        numbers.extend(re.findall(pattern, text))

    return numbers

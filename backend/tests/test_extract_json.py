"""
llm_client.extract_json: the single choke point between raw LLM text and every
structured consumer. Must tolerate the usual dirty outputs.
"""
import pytest

from app.services.llm_client import extract_json


def test_plain_json_object():
    assert extract_json('{"a": 1, "b": [1, 2]}') == {"a": 1, "b": [1, 2]}


def test_json_in_markdown_fence():
    text = 'Here you go:\n```json\n{"a": 1}\n```\nThanks!'
    assert extract_json(text) == {"a": 1}


def test_json_in_bare_fence():
    text = '```\n{"a": "x"}\n```'
    assert extract_json(text) == {"a": "x"}


def test_json_with_leading_and_trailing_prose():
    text = 'Sure! The result is {"ok": true, "n": 3} -- let me know.'
    assert extract_json(text) == {"ok": True, "n": 3}


def test_json_array_top_level():
    assert extract_json('[{"a": 1}, {"a": 2}]') == [{"a": 1}, {"a": 2}]


def test_json_array_with_prose():
    assert extract_json('items: [1, 2, 3] done') == [1, 2, 3]


def test_nested_braces_inside_strings():
    text = '{"text": "a {weird} value", "k": {"z": 1}}'
    assert extract_json(text) == {"text": "a {weird} value", "k": {"z": 1}}


def test_empty_and_whitespace_return_content_wrapper():
    assert extract_json("") == {"content": ""}
    assert extract_json("   \n ") == {"content": ""}


def test_not_json_at_all_returns_content_wrapper():
    text = "I cannot answer that."
    assert extract_json(text) == {"content": text}


@pytest.mark.parametrize("text", ['{"a": 1,}', '{a: 1}'])
def test_invalid_json_falls_through_to_wrapper(text):
    # Neither the direct parse, the fence, nor the brace regex yields valid JSON.
    assert extract_json(text) == {"content": text}

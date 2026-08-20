"""
Snippet ID compatibility helpers in petition_writer_v3 -- the foundation of
provenance correctness when old (block-based) ids meet the new registry.
"""
from app.services.petition_writer_v3 import (
    _build_snippet_lookup,
    _map_old_snippet_id_to_new,
    _parse_old_snippet_id,
)

REGISTRY = [
    {"snippet_id": "snp_C2_a3f5b1c2", "exhibit_id": "C2", "source_block_ids": ["p2_b5", "p2_b6"], "text": "x"},
    {"snippet_id": "snp_C2_deadbeef", "exhibit_id": "C2", "source_block_ids": ["p3_b1"], "text": "y"},
    {"snippet_id": "snip_legacy_1", "exhibit_id": "A1", "block_id": "p1_b0", "text": "z"},
]


# ---- _parse_old_snippet_id ------------------------------------------------

def test_parse_new_format():
    assert _parse_old_snippet_id("snp_C2_a3f5b1c2") == {"exhibit_id": "C2", "hash": "a3f5b1c2", "format": "new"}


def test_parse_old_format():
    parsed = _parse_old_snippet_id("snp_C2_p2_p2_b5_eadb0715")
    assert parsed == {
        "exhibit_id": "C2", "page": 2, "block": "b5", "block_full": "p2_b5",
        "hash": "eadb0715", "format": "old",
    }


def test_parse_old_format_with_dashed_exhibit():
    parsed = _parse_old_snippet_id("snp_B-10_p12_p12_b3_00ff00ff")
    assert parsed["exhibit_id"] == "B-10"
    assert parsed["page"] == 12
    assert parsed["block_full"] == "p12_b3"


def test_parse_rejects_garbage():
    assert _parse_old_snippet_id("") is None
    assert _parse_old_snippet_id(None) is None
    assert _parse_old_snippet_id("foo_C2_x") is None
    assert _parse_old_snippet_id("snp_C2") is None            # 2 parts
    assert _parse_old_snippet_id("snp_C2_p2_p2") is None      # 4 parts


def test_parse_old_format_page_edge_cases():
    # 'p' prefix but non-numeric -> int() fails -> None (documented behaviour)
    assert _parse_old_snippet_id("snp_C2_pX_p2_b5_eadb0715") is None
    # no 'p' prefix at all -> page defaults to 0
    parsed = _parse_old_snippet_id("snp_C2_x2_p2_b5_eadb0715")
    assert parsed is not None and parsed["page"] == 0


# ---- _map_old_snippet_id_to_new -----------------------------------------

def test_map_new_id_direct_lookup():
    assert _map_old_snippet_id_to_new("snp_C2_a3f5b1c2", REGISTRY)["text"] == "x"


def test_map_old_id_via_source_block_ids():
    assert _map_old_snippet_id_to_new("snp_C2_p2_p2_b6_ffffffff", REGISTRY)["text"] == "x"
    assert _map_old_snippet_id_to_new("snp_C2_p3_p3_b1_ffffffff", REGISTRY)["text"] == "y"


def test_map_old_id_via_block_id_fallback():
    assert _map_old_snippet_id_to_new("snp_A1_p1_p1_b0_ffffffff", REGISTRY)["text"] == "z"


def test_map_snip_prefix_direct():
    assert _map_old_snippet_id_to_new("snip_legacy_1", REGISTRY)["text"] == "z"
    assert _map_old_snippet_id_to_new("snip_nope", REGISTRY) is None


def test_map_wrong_exhibit_does_not_match():
    assert _map_old_snippet_id_to_new("snp_D9_p2_p2_b5_ffffffff", REGISTRY) is None


def test_map_unknown_returns_none():
    assert _map_old_snippet_id_to_new("snp_C2_00000000", REGISTRY) is None
    assert _map_old_snippet_id_to_new("garbage", REGISTRY) is None


# ---- _build_snippet_lookup ------------------------------------------------

def test_build_lookup_indexes_both_ways():
    lk = _build_snippet_lookup(REGISTRY)
    assert lk["by_new_id"]["snp_C2_deadbeef"]["text"] == "y"
    assert lk["by_exhibit_block"][("C2", "p2_b6")]["text"] == "x"
    assert lk["by_exhibit_block"][("C2", "p3_b1")]["text"] == "y"
    # snippets without source_block_ids do not pollute the block index
    assert ("A1", "p1_b0") not in lk["by_exhibit_block"]

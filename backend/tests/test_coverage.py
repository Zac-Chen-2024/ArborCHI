"""Evidence coverage overview (M13)."""
from app.services.coverage import compute_coverage

SNIPPETS = [
    {"snippet_id": "s1", "exhibit_id": "A1", "page": 1, "evidence_layer": "claim", "text": "x" * 200},
    {"snippet_id": "s2", "exhibit_id": "A1", "page": 2, "evidence_layer": "proof", "text": "b"},
    {"snippet_id": "s3", "exhibit_id": "B2", "page": 1, "evidence_layer": "significance", "text": "c"},
    {"snippet_id": "s4", "exhibit_id": "B2", "page": 3, "evidence_layer": "context", "text": "d"},
    {"snippet_id": "s5", "exhibit_id": "C1", "page": 1, "evidence_layer": "claim", "text": "e"},
]
LEGAL = {
    "arguments": [
        {"id": "arg-1", "standard_key": "awards", "sub_argument_ids": ["sa-1", "sa-2", "sa-3"]},
        {"id": "arg-2", "standard_key": "membership", "sub_argument_ids": ["sa-4"]},
    ],
    "sub_arguments": [
        {"id": "sa-1", "argument_id": "arg-1", "title": "two", "snippet_ids": ["s1", "s2"]},
        {"id": "sa-2", "argument_id": "arg-1", "title": "one", "snippet_ids": ["s3"]},
        {"id": "sa-3", "argument_id": "arg-1", "title": "none", "snippet_ids": []},
        {"id": "sa-4", "argument_id": "arg-2", "title": "m", "snippet_ids": ["s4", "ghost"]},
    ],
}


def test_compute_coverage_facts():
    cov = compute_coverage(LEGAL, SNIPPETS)
    assert cov["totals"] == {"snippets": 5, "assigned_snippets": 4, "unassigned_snippets": 1, "arguments": 2, "sub_arguments": 4}
    assert [u["snippet_id"] for u in cov["unassigned_snippets"]] == ["s5"]
    assert cov["unassigned_by_exhibit"] == {"C1": 1}
    awards = next(s for s in cov["standards"] if s["standard_key"] == "awards")
    assert awards["argument_count"] == 1 and awards["subargument_count"] == 3 and awards["snippet_count"] == 3
    assert [x["id"] for x in awards["single_evidence_subarguments"]] == ["sa-2"]
    assert [x["id"] for x in awards["empty_subarguments"]] == ["sa-3"]
    assert awards["layer_counts"] == {"claim": 1, "proof": 1, "significance": 1, "context": 0}
    assert awards["layer_gaps"] == ["context"]
    membership = next(s for s in cov["standards"] if s["standard_key"] == "membership")
    assert membership["layer_gaps"] == ["claim", "proof", "significance"]
    # unknown snippet ids are ignored, text is truncated
    assert cov["unassigned_snippets"][0]["text"] == "e"
    assert len(compute_coverage(LEGAL, SNIPPETS + [{"snippet_id": "long", "exhibit_id": "Z", "text": "y" * 500}])["unassigned_snippets"][-1]["text"]) == 163


def test_coverage_endpoint(client, victim_project):
    from app.services.snippet_recommender import save_legal_arguments
    save_legal_arguments(victim_project, LEGAL)
    r = client.get(f"/api/arguments/{victim_project}/coverage")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] and body["totals"]["sub_arguments"] == 4
    assert body["standards"][0]["standard_key"] == "awards"

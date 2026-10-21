from visiontriage.mcp_server import _stub_analyze


def test_stub_is_deterministic():
    first = _stub_analyze("defect_tile_007")
    second = _stub_analyze("defect_tile_007")
    assert first == second
    assert first[0].score >= 0.75


def test_clean_stub_scores_low():
    detections = _stub_analyze("good_tile_003")
    assert detections[0].label == "none"
    assert detections[0].score < 0.5

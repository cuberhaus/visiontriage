from visiontriage.graph import triage


def test_defect_image_is_flagged():
    report = triage("defect_bottle_001")
    assert report.verdict == "anomaly"
    assert report.detections[0].label == "scratch"
    assert "analyze_image" in report.tool_calls


def test_clean_image_is_normal():
    report = triage("good_bottle_014")
    assert report.verdict == "normal"

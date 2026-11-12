from visiontriage import tools
from visiontriage.bundle import load_bundle
from visiontriage.fixtures import build_fixture, build_visual_benchmark
from visiontriage.mcp_client import call_tool


def test_fixture_is_deterministic(tmp_path):
    a = build_fixture("slice_weakness", tmp_path / "a")
    b = build_fixture("slice_weakness", tmp_path / "b")
    assert (a / "predictions.jsonl").read_text() == (b / "predictions.jsonl").read_text()
    bundle = load_bundle(a)
    screw = tools.slice_metrics(bundle, "category", "screw")
    bottle = tools.slice_metrics(bundle, "category", "bottle")
    assert screw["fn"] > bottle["fn"]


def test_tools_and_clustering(tmp_path):
    bundle = load_bundle(build_fixture("quality_confound", tmp_path / "fx"))
    quality = tools.quality_breakdown(bundle)
    assert quality["bands"]["dark"]["fp"] > 0
    clusters = tools.cluster_failures(bundle, "fn")
    assert "clusters" in clusters
    examples = tools.list_examples(bundle, "fp", limit=3)
    assert examples["count"] >= 3


def test_duplicate_check_finds_cross_split_duplicates(tmp_path):
    bundle = load_bundle(build_fixture("leakage", tmp_path / "fx"))
    result = tools.duplicate_check(bundle)
    assert result["pair_count"] > 0
    pair = result["pairs"][0]
    assert pair["split_a"] != pair["split_b"]
    assert {pair["image_id_a"], pair["image_id_b"]} <= set(result["image_ids"])


def test_duplicate_check_quiet_without_cross_split_duplicates(tmp_path):
    bundle = load_bundle(build_fixture("slice_weakness", tmp_path / "fx"))
    assert tools.duplicate_check(bundle)["pair_count"] == 0


def test_visual_benchmark_labels(tmp_path):
    cases = build_visual_benchmark(tmp_path / "vb", per_kind=2)
    assert len(cases) == 10
    assert {c["attributes"][0] for c in cases} == {"clean", "dark", "crack", "contamination", "blur"}


def test_mcp_server_over_stdio(tmp_path):
    bundle_dir = build_fixture("slice_weakness", tmp_path / "fx")
    result = call_tool(str(bundle_dir), "slice_metrics",
                       {"dimension": "category", "value": "screw"})
    assert result["support"] >= 10
    images = call_tool(str(bundle_dir), "get_images", {"image_ids": ["bottle_0000"]})
    assert images["images"][0]["image_base64"]

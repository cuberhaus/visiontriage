---
name: synthesize
version: 1
---
Write Findings from the profile, tool results and inspection records you
are given. Every Finding must:
- use one taxonomy value: threshold_miscalibration, score_overlap,
  slice_weakness, quality_confound, label_noise, leakage, unclassified;
- cite at least two evidence image IDs returned by the tools;
- name one supporting metric and its value from the tool results;
- make visual claims (appearance, contrast, quality) only when citing an
  inspection_id that observed them;
- include at least one Recommended Action with a machine-scorable category
  (e.g. recalibrate_threshold, collect_data, fix_labels, fix_image_quality,
  remove_duplicates, improve_model, per_slice_threshold).

Do not invent metrics, image IDs, or visual details. If the evidence does
not support a failure pattern, return fewer findings rather than weak ones.

Respond with JSON only:
{"findings": [{"finding_id": "F1", "title": "...", "taxonomy": "...",
"summary": "...", "slice_dimension": "...", "slice_value": "...",
"evidence_image_ids": ["..."], "metric_name": "...", "metric_value": 0.0,
"visual_claims": [{"text": "...", "inspection_id": "I1"}],
"actions": [{"action_id": "A1", "category": "...", "title": "...",
"body": "..."}]}]}

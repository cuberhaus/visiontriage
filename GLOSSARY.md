# VisionTriage

VisionTriage analyses completed computer-vision evaluation runs to explain where a model fails, why it may be failing, and what should be done next.

## Language

**Evaluation Run**:
One execution of a model over a dataset that produces a Prediction for each evaluated image.
_Avoid_: Experiment, job, inference batch

**Run Bundle**:
The portable collection of Predictions, run metadata, and referenced images that represents one Evaluation Run for analysis.
_Avoid_: Dataset, results folder, run output

**Prediction**:
A model's output for one image, including its score and the corresponding ground truth.
_Avoid_: Detection, result, inference

**Slice**:
A subset of Predictions sharing a defined characteristic, such as a category, defect type, split, or image-quality range.
_Avoid_: Segment, cohort, filter result

**Failure Mode**:
A recurring, evidence-backed pattern of incorrect Predictions that can be described and acted upon.
_Avoid_: Error type, failure reason, bug

**Failure Taxonomy**:
The controlled set of categories used to classify Failure Modes, such as threshold problems, quality confounds, or label noise.
_Avoid_: Error labels, root-cause list

**Evidence Example**:
An individual Prediction and its referenced image cited in support of a Finding.
_Avoid_: Sample, proof, supporting image

**Finding**:
A documented conclusion from analysing an Evaluation Run, supported by metrics and Evidence Examples.
_Avoid_: Insight, observation, result

**Recommended Action**:
A proposed follow-up intended to address or further investigate a Finding.
_Avoid_: Fix, task, recommendation

**Failure Analysis Report**:
The human-reviewed account of an Evaluation Run's Findings and Recommended Actions.
_Avoid_: Triage report, incident report, model report

# Run Autopsy

Run Autopsy investigates why one anomaly-detection Experiment regressed against another, using the Experiments' own artefacts as evidence. It is a separate context from VisionTriage: terms below are canonical here and are not added to the root `GLOSSARY.md`.

## Language

**Experiment**:
One training and evaluation execution of an anomaly-detection model, together with the artefacts it produced and consumed.
_Avoid_: Evaluation Run (a VisionTriage term), job, inference batch

**Target Experiment**:
The Experiment under investigation in an Autopsy.
_Avoid_: Subject, bad run

**Baseline Experiment**:
The reference Experiment against which a Target Experiment is compared.
_Avoid_: Good run, reference run

**Experiment Artefact**:
A file that configures an Experiment or was produced by it, such as a config, log, metrics file, or result image.
_Avoid_: Attachment, output file

**Regression**:
A deterioration in a Target Experiment's measured performance relative to a Baseline Experiment.
_Avoid_: Failure, degradation

**Autopsy**:
An investigation of a Target Experiment, optionally against a Baseline Experiment, that produces ranked Autopsy Hypotheses.
_Avoid_: Triage, diagnosis

**Autopsy Hypothesis**:
A ranked causal claim about why a Regression occurred, supported by Experiment Artefact citations and not yet proven causal.
_Avoid_: Finding, root cause

**Confirmatory Experiment**:
An Experiment that changes only the suspected cause behind an Autopsy Hypothesis in order to test whether performance recovers.
_Avoid_: Rerun, validation run

**Autopsy Report**:
The human-reviewed record of an Autopsy's Hypotheses, their citations, and its stated unknowns.
_Avoid_: Failure Analysis Report, triage report

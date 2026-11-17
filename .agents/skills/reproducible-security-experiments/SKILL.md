---
name: reproducible-security-experiments
description: Make privacy/security experiments reproducible, statistically honest, and resistant to accidental cherry-picking.
---
# Reproducible security experiments

- Pin the code revision, configuration, dataset/fixture generation, environment, and random seeds where applicable.
- Separate synthetic fixtures, measured outputs, derived metrics, and narrative interpretation.
- Define hypotheses, baselines, acceptance criteria, exclusions, and stopping rules before running comparisons.
- Report sample counts, uncertainty, failures, and missing runs; do not discard unfavorable trials without a documented rule.
- Keep raw artifacts immutable and derive summaries with scripts that can be rerun.
- Verify that measurements correspond to the claimed commit and do not compare unlike workloads or budgets.
- Use synthetic data for privacy-sensitive experiments and avoid committing real identifiers or secrets.
- Re-run validation after changing code or experiment protocol; never present planned work as completed evidence.

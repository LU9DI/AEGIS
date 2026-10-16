# Normalized external trace dataset format

AEGIS now has a strict input validator at `anonlab.trace_dataset.load_normalized_jsonl`.
This supports research with legally obtained, consented, or otherwise appropriately licensed
traces. No external dataset is bundled or claimed to have been evaluated. The evaluator uses
a deliberately simple nearest-centroid baseline; it is not Deep Fingerprinting and does not
evaluate AEGIS defenses yet.

## JSONL schema

One JSON object per line, UTF-8. Each trace object must contain exactly these fields:

- `trace_id`: unique, non-empty string.
- `group_id`: non-empty capture/session group identifier. Keep correlated traces in the
  same group so a future train/test splitter can prevent session leakage.
- `label`: non-negative integer class label.
- `packets`: non-empty array of packet objects, in observed order.

Each packet must contain exactly:

- `direction`: integer `1` (client-to-site) or `-1` (site-to-client).
- `size_bytes`: integer from 1 to 65,535.
- `delta_ms`: finite, non-negative inter-packet delay in milliseconds.

Example (two records are required because the loader rejects a single-class dataset):

```jsonl
{"trace_id":"capture-001","group_id":"session-a","label":0,"packets":[{"direction":1,"size_bytes":512,"delta_ms":0.0},{"direction":-1,"size_bytes":1200,"delta_ms":12.5}]}
{"trace_id":"capture-002","group_id":"session-b","label":1,"packets":[{"direction":1,"size_bytes":480,"delta_ms":0.0},{"direction":-1,"size_bytes":980,"delta_ms":14.0}]}
```

## Validation and limitations

The loader rejects duplicate JSON keys, unknown/missing fields, duplicate trace IDs, invalid
packet values, non-finite numbers, invalid UTF-8, single-class datasets, and oversized input
(64 MiB total, 16 MiB per line, 100,000 traces, 100,000 packets per trace). It returns the
SHA-256 of the exact input bytes and retains `group_id`.

## Run the baseline evaluation

Install the project in editable mode, then run:

```bash
python -m pip install -e .
aegis-privacy-eval --trace-dataset path/to/traces.jsonl --seed 42 --output experiments/external-baseline.json
```

The evaluator uses a group-disjoint train/test split: all traces with the same `group_id`
stay together, and every label must occur in both sets. If labels are confounded with groups
or a suitable split cannot be found, evaluation fails rather than falling back to a trace-level
split. It runs a simple nearest-centroid attacker on both the undefended traces and a toy
size-bucketing/cover transform, reusing the exact same holdout for a paired comparison. You can
change the toy parameters with `--trace-bucket-bytes` (minimum 64) and `--trace-cover-rate`
(0..1). The output records the input SHA-256, counts, hashed group assignments, confusion matrix,
per-class metrics, byte overhead, and the difference in attacker accuracy. Raw group IDs are not
included in the report. Existing output files are never overwritten.

This remains an **experimental toy comparison**, not a production defense evaluation. Packet
timing effects, adaptive attackers, alternative classifiers, realistic capture diversity, and
comparisons remain future work. A change in this classifier's accuracy is not by itself proof
that privacy improved. A group ID is only as meaningful as the
dataset curator's definition: unrelated sessions must not share a group, and correlated traces
must not be assigned separate groups. Before publishing results, document the dataset publisher,
collection method, licensing/consent, preprocessing, class mapping, and known biases. Remove or
pseudonymize identifiers and do not commit sensitive raw captures to the repository. A dataset
digest and group-disjoint split do not establish dataset representativeness or anonymity.

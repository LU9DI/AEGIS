# Normalized external trace dataset format

AEGIS now has a strict input validator at `anonlab.trace_dataset.load_normalized_jsonl`.
This is infrastructure for future research with legally obtained, consented, or otherwise
appropriately licensed traces. It does **not** turn the synthetic fingerprinting harness
into a real-trace evaluation, and no external dataset is bundled or claimed to have been
evaluated.

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

The loader is not yet connected to `privacy_eval.py`; it does not select a group-aware split,
run an attacker, evaluate padding, or establish representativeness. Dataset publishers,
collection method, licensing/consent, preprocessing steps, class mapping, and a leakage-safe
group split must be reviewed before reporting real-trace results. Remove or pseudonymize
identifiers and do not commit sensitive raw captures to the repository.

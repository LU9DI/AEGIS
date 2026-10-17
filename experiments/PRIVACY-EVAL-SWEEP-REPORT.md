# Privacy evaluation sweep — analysis and limitations

Status: **synthetic harness analysis only.** This report interprets committed experiment
artifacts. It is not evidence about anonymity, performance, or security on any real network.

## Artifacts analyzed

| Artifact | Schema | Run | Size | SHA-256 |
| --- | --- | --- | --- | --- |
| `experiments/privacy-eval-sweep.json` | 1 | seed 20261014 | 7 861 B | `F037C540DE4C2F26298609A5D1FBE7663F05066D5776A5770FEFF084EC539382` |
| `experiments/privacy-eval-v2-stability.json` | 2 | primary seed 20261014 + stability seeds 20261014/15/16/17/20 | 27 175 B | `F2CC2B27D9BB24289C075F7C5533A2C9CD4F02A71BD337EA84A2A74B56B45972` |

Reproduction (the harness refuses to overwrite an existing output file; use a new path):

```bash
aegis-privacy-eval --seed 20261014 --output experiments/privacy-eval-sweep.json
aegis-privacy-eval --seed 20261014 --stability-seeds 20261014,20261015,20261016,20261017,20261020 --output experiments/privacy-eval-v2-stability.json
```

Reproducibility check: two independent runs of the schema-1 command produced byte-identical
files (the SHA-256 above was confirmed on both runs).

## What is measured

- 500 synthetic randomized path selections over candidate routes with synthetic
  latency-detour and AS labels (acceptance rule: entry AS ≠ exit AS; detour within budget).
- A toy website-fingerprinting attacker: nearest-centroid classifier over synthetic
  per-site delay features, 6 sites, chance accuracy 1/6 ≈ 0.1667.
- A toy padding model on the client-to-entry link (size buckets + cover traffic),
  with byte overhead measured against the unpadded baseline.

None of these values are measurements of a deployed network. The features are model
outputs; the classifier is deliberately simple.

## Sweep results (schema 1, seed 20261014)

| bucket (B) | cover rate | byte overhead | fingerprinting accuracy |
| --- | --- | --- | --- |
| 128 | 0.00 | 9.66 % | 1.0000 |
| 128 | 0.25 | 14.51 % | 1.0000 |
| 128 | 0.50 | 19.33 % | 1.0000 |
| 128 | 0.75 | 24.09 % | 1.0000 |
| 128 | 1.00 | 29.03 % | 1.0000 |
| 256 | 0.00 | 19.15 % | 1.0000 |
| 256 | 0.25 | 28.86 % | 1.0000 |
| 256 | 0.50 | 38.49 % | 1.0000 |
| 256 | 0.75 | 48.02 % | 1.0000 |
| 256 | 1.00 | 57.90 % | 1.0000 |
| 512 | 0.00 | 40.34 % | 1.0000 |
| 512 | 0.25 | 59.75 % | 1.0000 |
| 512 | 0.50 | 79.02 % | 1.0000 |
| 512 | 0.75 | 98.07 % | 1.0000 |
| 512 | 1.00 | 117.83 % | 1.0000 |
| 1024 | 0.00 | 55.20 % | 1.0000 |
| 1024 | **0.25** | 94.03 % | **0.8929** |
| 1024 | **0.50** | 132.55 % | **0.8869** |
| 1024 | **0.75** | 170.66 % | **0.9583** |
| 1024 | 1.00 | 210.18 % | 1.0000 |

### Findings

1. **The classifier is insensitive to padding below bucket 1024.** All 16 configurations
   with buckets 128–512 sit at perfect accuracy for every cover rate. The synthetic
   features (per-site delay histograms and counts) simply do not change enough in that
   regime to move the nearest-centroid decision. Perfect accuracy here says nothing about
   the quality of the padding model.
2. **The only accuracy dips form a non-monotonic artifact.** Accuracy drops (0.887–0.958)
   appear only at bucket 1024 with partial cover (0.25–0.75), while cover 1.0 returns to a
   perfect 1.0 and costs 210 % overhead. A real defense that helped should not get *worse*
   from 0.25 to 0.50 cover and then *perfect* at 1.0. This pattern is consistent with how
   the toy feature pipeline compresses delay bins at a particular bucket/cover combination,
   not with any defense property.
3. **Overhead spans 9.66 % (128 B, no cover) to 210.18 % (1024 B, full cover).** The
   schema-1 default padded setting (256 B, cover 0.25) costs 28.86 % bytes.
4. **No configuration can be recommended from this data.** Picking, e.g., 1024/0.5 because
   its accuracy "dropped" would be reading noise in a synthetic pipeline. The artifact's own
   `defense_sweep_interpretation` field states this.

## Stability across seeds (schema 2, 5 seeds)

Per-seed headline results (fixed padded setting: 256 B bucket, cover 0.25):

| seed | plain accuracy | padded accuracy | padded overhead |
| --- | --- | --- | --- |
| 20261014 | 1.0000 | 1.0000 | 28.86 % |
| 20261015 | 1.0000 | 0.9940 | 29.24 % |
| 20261016 | 1.0000 | 1.0000 | 29.14 % |
| 20261017 | 1.0000 | 1.0000 | 28.95 % |
| 20261020 | 1.0000 | 1.0000 | 29.06 % |

- Plain accuracy: min = max = mean = 1.0, pstdev = 0.
- Padded accuracy: min 0.9940, mean 0.9988, pstdev 0.0024. The single dip is exactly one
  misclassified test sample (1/168 = 0.0060); it is sampling noise, not a seed-dependent
  regime.
- Padded overhead: 28.86 %–29.24 %, pstdev 0.14 pp — deterministic model, small drift from
  the random sampling of sites/paths.

The schema-2 sweep repeats all 20 configurations under all 5 seeds. The bucket-1024,
cover-0.25/0.50/0.75 band stays inside 0.887–0.964 across seeds (still non-monotonic, still
a synthetic-pipeline artifact), while every other configuration stays at ≥ 0.994. **Any
single-seed accuracy difference below ~0.006 in this harness is noise and should not be
interpreted.**

## Split hygiene and AS policy (schema 2 additions)

- Train/test split: 312 train / 168 test samples, stratified, shared by the plain, padded
  and all 20 sweep measurements in a run. Artifact records `train_digest`/`test_digest`
  (`fed7b7435c3790c5` / `c51d7d8490b4d522` for this run); the harness validates the split
  and aborts on overlap or out-of-range indices, so measurements cannot silently leak.
- Path selection now uses a stricter default policy: any autonomous system appearing at
  more than one path position rejects the candidate (entry AS reappearing as a middle
  relay, entry = exit, repeated middle AS, …).
- Evidence in the artifact: 6 candidates instead of 5, the new adversarial candidate
  `bad-repeated-middle-as` rejected together with `bad-shared-as` (both selected 0 times
  out of 500), `as_conflict_rejections` naming each rejection, and
  `selected_paths_with_as_conflict: 0`. Accepted-path counts (regional-a 177, regional-b
  178, regional-c 145) are unchanged, which is expected: the strict policy only removed
  candidates that were already unsuitable, and the artifact now proves that explicitly.

## Limitations (explicit)

- Synthetic labels, synthetic sites, synthetic candidate routes, synthetic AS/detour
  values. No packet captures, no real traces, no real topology.
- Nearest-centroid classifier only — not Deep Fingerprinting, not a Tor comparison, no
  hyperparameter search, no adversarial attacker adaptation.
- Latency and throughput are **not measured** by this harness; the artifact's
  `not_measured` block states this. Delay values are model parameters.
- Seed spreads are sampling-seed variation only; they are not confidence intervals and do
  not transfer to real traffic.
- The privacy-eval harness shares no code path with the networking prototypes; it does not
  exercise the onion/telescoping implementation.

## What would change these conclusions

1. Import real trace datasets (with the strict validation a loader must enforce) and a
   stronger attacker (at minimum a DF-style model), keeping the same split-hygiene rules.
2. Calibrate route/AS data from public data instead of synthetic generators.
3. Declare an explicit objective (overhead budget vs. accuracy target) before selecting any
   configuration.

Until then, this sweep is a reproducible harness check — useful for detecting changes in
the harness itself, not for judging a defense.

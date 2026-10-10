# Validation — WINDOW_UPDATE timer cross-profile follow-up v0.22.0

Date: 2026-10-09

- Intercontinental profile: 6/6 runs completed; integrity, relay observability, cleanup, bounded telemetry, configured parameters, and late-flow overlap checks passed.
- Constrained profile: 6/6 runs are present in valid JSON; the same per-run checks passed. The wrapper did not return a clean process exit within the outer execution budget; the complete JSON was parsed, and all six rows plus aggregate checks were validated.
- Full `unittest` suite with `ResourceWarning` promoted to errors: 154 passed in 24.167 s. One asyncio slow-task diagnostic appeared, but the suite completed successfully and no ResourceWarning was raised.
- Full `pytest` suite: 156 passed, 23 subtests passed in 24.50 s.
- Cross-profile result: two trials per timer/profile, not statistically conclusive. Keep the default timer at 2 ms.
- Version remains 0.22.0; this is a research/benchmark package, not a production readiness claim.

Commands used for suite validation:

```bash
PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -q
PYTHONPATH=src pytest -q
```

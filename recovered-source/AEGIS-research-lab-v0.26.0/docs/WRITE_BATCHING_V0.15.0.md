# Acknowledged write batching — v0.15.0 (experimental)

## Change

The client-to-destination `DuplexCircuitStream.write()` operation now accepts payloads up to 64 KiB per command. In v0.14.0, the write cap was 16 KiB. Each write still waits for its destination-write acknowledgement, so one full 64 KiB application write now uses one acknowledged command rather than four.

Response-side event frames remain capped at 16 KiB. The initial read-credit window remains 64 KiB per stream, with the previously documented maximum and flow-control behavior. The 64 KiB write cap is explicit to bound the payload of a single command. This change does not pipeline or remove acknowledgements.

## Why change this?

The v0.14.0 benchmark used eight 64 KiB streams but split each stream's application writes into 16 KiB commands. Per-command acknowledgements inserted additional circuit round trips into the data path. Batching amortizes that protocol overhead over more useful payload bytes.

## Results in this lab run

The five-trial paired benchmark measured a median of 152.46 Mb/s at 16 KiB writes and 193.71 Mb/s at 64 KiB writes (+27.1%). All payload-integrity, relay-observability, and cleanup checks passed in both groups. Full ranges and method are in `../experiments/WRITE_BATCHING_REPORT_V0.15.0.md`; raw trials are in `../experiments/write-batch-v0.15.0.json`.

These numbers apply only to one host with IPv4 loopback listeners, Python scheduling, and this exact payload profile. They do not forecast WAN performance, prove fairness, compare anonymity-equivalent designs, or show parity with Tor. The direct TCP reference is unencrypted and does not provide anonymity.

## Limits and risks

- One command may transiently hold up to 64 KiB of application payload, plus framing and AEAD overhead.
- Aggregate memory use is still a function of active streams and queued work; this optimization is not a complete global resource bound.
- Write acknowledgement still occurs for every batch. Larger windows, pipelining, and coalesced acknowledgements would need their own sequence/cancellation design and adversarial tests.
- Response events stay small so event queues and the 64 KiB read-credit window remain bounded.
- The custom transport remains loopback-only, unaudited, and not production-safe.

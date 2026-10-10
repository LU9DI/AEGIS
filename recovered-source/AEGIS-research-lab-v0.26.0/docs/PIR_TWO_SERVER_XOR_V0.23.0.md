# AEGIS v0.23.0 — two-server XOR PIR reference prototype

## Status

Implemented as an in-process reference construction in `src/anonlab/pir.py`, exposed as `aegis-pir-demo`. It retrieves a selected fixed-width record from two logically separate, identical database replicas using XOR shares of a one-hot index vector. The CLI runs both server computations locally to test correctness; it is not a deployed distributed service.

## Protocol

Let the database be `D[0..N-1]`, with equal-width rows. The client samples a cryptographically random N-bit mask `r`. It sends `qA = r` to server A and `qB = r XOR e_i` to server B, where `e_i` has a single bit set at the requested row. Each server XORs the rows selected by its query. The client XORs the two responses; all rows cancel except `D[i]`.

For either server alone, its query vector is uniform independent of `i`. The tests exhaust all masks on a small toy database to check this distribution property exactly. This construction is information-theoretic for the individual query, under the stated replicated-data model.

## Cost and assumptions

- The query vector is N bits, or `ceil(N/8)` bytes, uploaded to each server.
- Each server scans the full table and XORs selected records: O(N) row operations per query. Response size is one row.
- Both servers must hold identical database snapshots. **If they collude, `qA XOR qB` reveals the requested index.** The servers can also observe client IP/timing unless the requests use a separate anonymity layer.
- Fixed-width records and database ordering must be agreed; side channels, malformed replicas, database changes and request/response authentication are not solved here.
- PIR is a record-retrieval primitive, not a way to return arbitrary entire web pages at line speed. General web content would require a defined indexed dataset/chunk manifest, cache/version semantics and substantial measurement of communication/computation costs.
- FHE is not included. Homomorphic encryption can enable computation on ciphertext for supported circuits but should not be assumed to make arbitrary browsing cheap or to hide all metadata.

## Run

```bash
PYTHONPATH=src python -m anonlab.pir --records 64 --index 17
```

## References

- Chor et al., “Private Information Retrieval”, JACM (1998), abstract and model of replicated servers: https://doi.org/10.1145/293347.293350
- Recent PIR overview discussing communication and server-computation costs: https://link.springer.com/chapter/10.1007/978-981-96-1218-5_24

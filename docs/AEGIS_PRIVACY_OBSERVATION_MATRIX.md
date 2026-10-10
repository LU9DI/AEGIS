# AEGIS privacy observation matrix — baseline requirements

Status: threat-model worksheet for measurement design; **not an anonymity proof and not a claim that the current implementation satisfies every property**.

## Scope and assumptions

This matrix describes information that network participants can generally observe in the documented AEGIS topology. Exact fields depend on the deployed transport and configuration and must be verified against packet captures and runtime instrumentation before a production claim. A three-hop circuit is not, by itself, a guarantee against a global or colluding observer.

- **Client**: endpoint initiating a circuit.
- **Entry relay**: first relay receiving a client connection.
- **Middle relay**: relay forwarding traffic between entry and exit.
- **Exit relay**: final relay opening the connection to the destination.
- **Destination**: server the client is communicating with.
- **Network observer**: party able to observe one or more links; capability ranges from one-link passive observation to broad traffic correlation.
- **Colluding relays**: two or more relays sharing their observations outside the protocol.

## Observation matrix

| Observer | Usually visible | Usually not directly visible from that link alone | Important residual risk / test |
|---|---|---|---|
| Client | Destination intent, its own requests and timing, selected route if exposed by client API | Other clients' traffic and relay-private state | Client endpoint compromise defeats network-layer privacy |
| Entry relay | Client network address/connection peer, connection timing/volume, next hop | Plaintext destination application content when payload is protected end-to-end; final destination if route construction hides it | Entry can correlate client arrival with traffic leaving the entry; confirm no stable user ID or target index is logged |
| Middle relay | Previous and next hop, timing, byte counts, flow duration | Client address and final destination under a correctly separated multi-hop path | Timing/volume correlation across both adjacent links; verify circuit isolation and that logs do not join flows with stable IDs |
| Exit relay | Destination address/port and timing; application plaintext if end-to-end encryption is absent | Client network address when routing separation works and no collusion/correlation bridges it | Exit can observe destination metadata and potentially content; verify TLS remains end-to-end and DNS behavior is documented |
| Destination | Exit-side peer address, requests and any application metadata disclosed by the client | Client address behind a correctly functioning relay path, absent external correlation | Account login, browser fingerprinting and application identifiers can identify a user independently of the network |
| Passive observer of one link | Endpoints of that link, packet timing/size/volume, transport metadata visible on that link | Encrypted payload contents; endpoints not on that observed link | Fingerprinting and traffic analysis; measure distinguishability and do not infer anonymity from encryption alone |
| Observer of client access and exit traffic | Timing/volume at both sides if both vantage points are available | Direct cryptographic linkage is not automatically available | End-to-end traffic correlation remains a major risk; test realistic observation windows and report false-match rates |
| Two colluding PIR replicas | Their own query masks and responses; XOR of both masks in the current two-server construction | Neither replica alone is intended to learn the selected index under the protocol assumptions | Collusion reconstructs the target one-hot mask; verifiable computation does not remove this privacy limitation |
| One malicious PIR replica | Its own mask, request metadata, and ability to return a malformed/fabricated answer | The other replica's mask absent collusion | TLS authenticates the endpoint, not answer correctness; current client has no cryptographic proof of correct computation |

## Required measurement/reporting fields

For each tested topology, record:

1. Number of hops, role of each relay, whether relays are independently operated, and which observer vantage points are simulated.
2. Exact fields available to each observer: address/port, protocol metadata, byte count, packet/record sizes, timestamps, destination, DNS behavior, and application content where applicable.
3. Whether application-layer encryption is end-to-end, separate from relay transport encryption.
4. Whether logs contain target index, PIR masks, record contents, stable flow identifiers, user identifiers, or correlatable request IDs. A “no” must be established by code review and tests, not assumed.
5. Traffic-correlation experiment design: observation window, sample count, baseline/attack strategy, true-positive rate, false-positive rate, and confidence intervals. Keep synthetic and real-network results separate.
6. Adversary capabilities: single-link observer, entry observer, exit observer, entry+exit collusion, relay collusion, destination collusion, and global passive observer.
7. Failure cases: relay compromise, malicious exit, traffic bursts, low-entropy destinations, reconnects, retries, circuit reuse, and long-lived flows.

## Acceptance rules

- Never call a route-knowledge unit test an anonymity proof.
- Never equate TLS confidentiality with destination anonymity or correct PIR computation.
- Never claim “no logs” or “no identifiers” without auditing all logging and telemetry paths.
- Never claim protection against a global passive observer without a clearly specified and independently reviewed argument.
- Report measured privacy/traffic-analysis results separately from design expectations and simulator output.
- For PIR, keep the two-server non-collusion assumption explicit and keep unverified remote answers marked experimental/fail-closed until a real verifier is implemented.

## Open gaps

- Current benchmark harnesses run locally/loopback and do not establish privacy under independent real-world relays.
- There is no completed traffic-correlation evaluation with false-positive/false-negative analysis.
- No cryptographic proof-of-correct-computation is currently integrated into the private PIR query path.
- This worksheet does not establish that every field listed above is currently captured by AEGIS; instrumented packet/metadata audits are required to validate the matrix.

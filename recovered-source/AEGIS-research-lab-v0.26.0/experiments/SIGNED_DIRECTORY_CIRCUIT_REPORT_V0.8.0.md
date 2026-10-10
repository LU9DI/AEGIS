# Signed directory → telescoping circuit integration report — v0.8.0

## Result

The first-party test path now verifies all proposed relay descriptors before constructing any circuit descriptor. It then uses the verified descriptors to build a three-hop loopback circuit over a single client-to-entry socket and sends an echo payload through the circuit.

The integration tests verify:

- all three relays are authorized by the same pinned test authority and their descriptors are signed by their own relay identities;
- each descriptor binds the relay identity digest, onion key, endpoint, protocol, validity interval, sequence and serial;
- the client creates one direct socket to the entry and extends the middle and exit hops through the existing circuit;
- the payload returns intact, while the entry and middle relay observation records do not contain the application echo destination port;
- changing a signed descriptor endpoint causes signature verification to fail before the client opens a circuit socket;
- revoking a relay prevents route materialization before a client circuit socket is opened.

## Validation performed

- `python -m unittest discover -s tests -v`: **67 tests passed**.
- `python -m compileall -q src tests`: passed.
- `python -m anonlab.directory_demo`: passed; reports descriptor certification, onion key rotation, rollback rejection and revocation rejection.
- Wheel `rea_anon_lab-0.8.0-py3-none-any.whl` built using the locally installed build backend without network isolation, installed into an isolated target directory, and its `anonlab.directory_demo` module executed successfully.

## Interpretation and limitations

This report validates software behavior in a same-host loopback testbed. It does not prove anonymity, defend against global traffic correlation, or provide public-network readiness. The authority key is generated for each test and is not a persistent production trust root. The verifier's descriptor sequence and revocation epoch state is process-local. The circuit code still exposes legacy APIs accepting manually constructed descriptors, so signature verification is a supported first-party construction path rather than a mandatory application-wide policy gate. Relay-to-relay transport authentication, persistent anti-rollback state, trust-root rotation, a distributed directory, a reviewed key schedule, general bidirectional streams and independent security audit are not complete.

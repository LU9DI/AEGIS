# AEGIS brand transition

**Effective identity:** AEGIS — **A**nonymous **E**ncrypted **G**arlic-routed **I**nternet **S**hield.

The name adopts the historical aegis/égide metaphor: a protective shield associated with Zeus and Athena, here used to describe a dynamic defense against mass surveillance. The acronym is the project identity and architectural direction.

## What changed

- The public-facing project name, README, CLI description and fresh benchmark metadata now use AEGIS.
- The Python distribution is `aegis-anon-lab`; the Python import package remains `anonlab`.
- New AEGIS-prefixed console commands are provided. Previous `rea-anon-*` commands remain available as compatibility aliases.
- Old benchmark JSON and reports retain their MALEBOLGE labels. Those are historical observations; rewriting their metadata would blur when each result was produced and under what project identity.

## What deliberately did not change

The `MALEBOLGE/...` protocol domain-separation strings, AAD prefixes, relay-identity hash domain, legacy directory protocol ID (`malebolge-lab-ntor-v1`), and KDF context are preserved. These byte strings participate in authentication, identity derivation, or key expansion. A naming-only change must not silently modify them, because doing so could alter wire compatibility or derived keys. Any protocol namespace migration needs an explicit protocol version, dual-stack/interoperability behavior, and cryptographic review.

## Capability honesty

The acronym includes “Garlic-routed,” but the current implementation does **not** yet implement garlic routing in the strict garlic-clove sense (bundling/delivering multiple messages inside one encrypted wrapper). The current lab implements experimental layered per-hop encryption and multi-hop relay circuits, with local loopback benchmarks. The name describes the intended direction; it is not a security property or feature-completion claim.

## Known limitations

The protocol remains custom and unaudited. Loopback shaper tests do not establish real-WAN behavior, resistance to a global passive observer, traffic-analysis resistance, or production-grade anonymity. No change to protocol version or security claims is made by this rebrand.

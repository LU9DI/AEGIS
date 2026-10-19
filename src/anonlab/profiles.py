"""Reference profiles for controlled, explicitly hypothetical experiments."""

from .model import Hop, NetworkProfile

# These are not measurements of the live Tor network or the public internet.
# They are deliberately transparent modeling assumptions for the first lab run.
DIRECT = NetworkProfile(
    name="direct_reference",
    hops=(Hop(latency_ms=11, jitter_ms=3, bandwidth_mbps=500),),
    description="Direct-connection reference; not anonymous.",
)

TOR_LIKE = NetworkProfile(
    name="onion_reference",
    hops=(
        Hop(latency_ms=34, jitter_ms=10, bandwidth_mbps=20),
        Hop(latency_ms=32, jitter_ms=10, bandwidth_mbps=15),
        Hop(latency_ms=38, jitter_ms=12, bandwidth_mbps=10),
    ),
    description="Simplified three-hop onion-routing reference; illustrative parameters, not live Tor measurements.",
)

# An optimistic target: dedicated/high-capacity hops, not an implemented
# protocol and not a claim that such a network already exists at these rates.
CANDIDATE_FAST = NetworkProfile(
    name="candidate_fast_hypothesis",
    hops=(
        Hop(latency_ms=12, jitter_ms=4, bandwidth_mbps=250),
        Hop(latency_ms=12, jitter_ms=4, bandwidth_mbps=150),
        Hop(latency_ms=14, jitter_ms=5, bandwidth_mbps=100),
    ),
    description="Hypothetical high-capacity three-hop design used to test sensitivity to network assumptions.",
)

CANDIDATE_NOISE = NetworkProfile(
    name="candidate_independent_noise_hypothesis",
    hops=CANDIDATE_FAST.hops,
    cover_mode="independent_noise",
    cover_ratio_per_edge=1.5,
    description=(
        "Optimistic independent edge-noise ceiling. This assumes traffic is mixed/aggregated so "
        "the noise at the two observation points is independent; a single tunnel that forwards its "
        "own dummy packets does not automatically provide this property."
    ),
)

CANDIDATE_FIXED_RATE = NetworkProfile(
    name="candidate_fixed_rate_hypothesis",
    hops=CANDIDATE_FAST.hops,
    cover_mode="fixed_rate",
    fixed_rate_mbps=20,
    description=(
        "Idealized fixed-rate padded tunnel. Assumes a constant observable rate and enough path "
        "capacity; it does not model direction leaks, packet metadata, failures, or a global observer's "
        "other side channels."
    ),
)

DEFAULT_PROFILES = (DIRECT, TOR_LIKE, CANDIDATE_FAST, CANDIDATE_NOISE, CANDIDATE_FIXED_RATE)

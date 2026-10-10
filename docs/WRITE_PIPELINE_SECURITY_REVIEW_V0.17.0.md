# v0.17.0 bounded WRITE pipeline — security review notes

## Controls added

1. Client pipeline depth is validated as an integer from 1 to 4; booleans are
   rejected despite being integer subclasses in Python. A single API call also
   has a 4 MiB payload cap and 512-command cap to avoid excessive tiny chunks.
2. Each chunk is still individually encoded, AEAD-encrypted per hop, assigned
   unique monotonically increasing per-hop sequence numbers, and matched to a
   registered `(sequence, stream_id)` response future.
3. The client checks that a whole batch will not exceed any hop's command budget
   before writing its first frame.
4. Relay handlers reserve per-stream command/byte budgets and per-circuit
   aggregate pending bytes before scheduling asynchronous ACK work.
5. Relay downstream frames are enqueued in parent receive order. ACKs may return
   out of order but response dispatch uses sequence/stream correlation.
6. `HALF_CLOSE` and `CLOSE` are serialized with client writes and rejected at a
   relay if earlier WRITE acknowledgements remain pending.
7. Relay connection teardown cancels and joins the pending write tasks; errors
   fail the circuit connection closed rather than sending partial success.

## Residual risks

- The custom protocol is not independently audited and is not Tor-wire
  compatible.
- Per-process pending-byte counters bound tracked payloads but do not exactly
  model memory held by Python copies, encryption buffers, asyncio transports,
  kernel socket buffers, or caller-owned data.
- A remote peer can deliberately exhaust the per-circuit budgets and force
  connection closure. Global admission across all circuits still depends on the
  existing connection and stream limits.
- Write `drain()` acknowledgements indicate local transport-buffer progress;
  they do not prove the remote application durably consumed or processed bytes.
- Response acknowledgements can be reordered; this implementation depends on
  authenticated sequence demultiplexing and retains no general retransmission
  or resume protocol.
- No WAN, packet-loss, congestion, stream-fairness, global-observer, or
  traffic-correlation validation is included.

## Required before external use

Use a standardized, reviewed stream transport where practical; obtain an
independent protocol/implementation review; add hostile peer fuzzing and
resource-exhaustion tests; test across independent hosts under shaped latency,
loss, and congestion; and define shutdown, timeout, and cancellation semantics
for every outstanding command. Do not expose these testbed listeners to the
public Internet.

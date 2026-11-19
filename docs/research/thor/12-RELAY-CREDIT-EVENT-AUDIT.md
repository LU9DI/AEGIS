# 12 — Auditoria do caminho de crédito, ACK e agregação de eventos (THOR P2, Fase 1)

- **Branch**: `perf/thor-relay-credit-event-lab`
- **Base obrigatória**: `baecf8375704ad58d544712a410de725b1689360` (topo do P1)
- **Código auditado**: `src/anonlab/telescoping.py` nesta branch (as linhas abaixo são desta árvore; as três primeiras linhas da tabela de símbolos são as constantes de produção, inalteradas)
- **Método**: leitura linha a linha do caminho real + execução do caminho real (relays, handshakes, AEAD e framing reais) em loopback, com as métricas de relay que o protótipo já expõe (`collect_relay_metrics`).
- **Tier**: `loopback` (um host, relays no mesmo processo Python). Nada aqui é WAN, Tor ou prova de anonimato.

Este documento responde à Fase 1: **quais mensagens esperam resposta antes de prosseguir, quais podem ser processadas de forma independente, e como separar as seis categorias de espera** sem somar métricas concorrentes como se fossem tempo de parede aditivo.

## 1. Constantes em jogo

| Símbolo | Valor | Linha | Papel |
|---|---|---|---|
| `STREAM_CHUNK_BYTES` | 16 KiB | `telescoping.py:105` | tamanho de cada evento de resposta gerado pelo exit (e fatia devolvida por `read_chunk`) |
| `INITIAL_STREAM_WINDOW_BYTES` | 64 KiB | `:116` | crédito inicial de leitura por stream |
| `MAX_STREAM_WINDOW_BYTES` | 256 KiB | `:117` | teto absoluto de crédito (relay recusa acima) |
| `WINDOW_UPDATE_BATCH_BYTES` | 64 KiB | `:120` | limiar de bytes consumidos para emitir `WINDOW_UPDATE` |
| `WINDOW_UPDATE_MAX_DELAY_SECONDS` | 2 ms | `:121` | prazo para *flush* de crédito parcial (anti-starvation) |
| `MAX_STREAM_EVENT_QUEUE` | 8 | `:122` | fila de eventos de um stream antes de `START` |
| `MAX_PIPELINE_DEPTH` | 4 | `:110` | comandos `WRITE` em voo por stream |
| `MAX_DATA_BYTES` | 1 MiB | `:86` | payload máximo de um comando |

## 2. Diagrama de sequência (3 hops, leitura de 256 KiB em chunks de 16 KiB)

```
cliente                 guard (hop1)            middle (hop2)           exit (hop3)          destino TCP
   |  O OPEN_STREAM(seq0)   |                        |                       |                    |
   |----------------------->|  F OPEN (seq0)         |                       |                    |
   |                        |----------------------->|  F OPEN (seq0)        |                    |
   |                        |                        |---------------------->|  connect()         |
   |                        |                        |                       |------------------->|
   |                        |                        |                       |<--- STREAM_OPENED  |
   |<--- STREAM_OPENED -----|<--- STREAM_OPENED -----|                       |                    |
   |  B START (seq1)        |                        |                       |                    |
   |----------------------->|  F START (seq1)        |                       |                    |
   |                        |----------------------->|  F START (seq1)       |                    |
   |                        |                        |---------------------->| read_task = pump() |
   |<--- STREAM_STARTED ----|<--- STREAM_STARTED ----|                       |                    |
   |                        |                        |                       | credit=64 KiB      |
   |  W WRITE (seq2, 16 KiB)|                        |                       |                    |
   |----------------------->|  F WRITE(seq2)         |                       |                    |
   |                        |----------------------->|  F WRITE(seq2)        |                    |
   |                        |                        |---------------------->| write()+drain()    |
   |                        |                        |                       |------------------->|
   |                        |                        |                       |<--- echo 16 KiB ---|
   |                        |                        |                       | read(16 KiB)       |
   |                        |                        |<--- EVENT(seq0) ------| seal(response_key) |
   |                        |<--- EVENT(seq0) -------|                       |                    |
   |<--- EVENT(seq0) -------|                        |                       |                    |
   |  read_chunk() -> 16 KiB; pending_credit += 16 KiB                        |                    |
   |  ... (4 chunks) ... quando pending_credit >= 64 KiB:                     |                    |
   |  V WINDOW_UPDATE(64 KiB)                                                 |                    |
   |----------------------->| F WINDOW_UPDATE        |                       |                    |
   |                        |----------------------->|  F WINDOW_UPDATE      |                    |
   |                        |                        |---------------------->| read_credit += 64 KiB (<= 256 KiB) |
   |<--- WINDOW_UPDATED ----|<--- WINDOW_UPDATED ----|                       |                    |
   |  (o cliente aguarda este ACK antes de devolver o próximo chunk)          |                    |
```

Duas variantes do caminho:

- **Uma-shot** (`CircuitStream`/`request_echo`, workloads P0 bulk): o cliente envia um comando `D` (≤1 MiB) e recebe os eventos; cada hop reencaminha e espera o hop seguinte.
- **Duplex** (`DuplexCircuitStream`): `WRITE` é confirmado por `WROTE`; o relay pode ter até 4 `WRITE` em voo por stream (`MAX_PIPELINE_DEPTH`), mas cada comando continua com correlação 1:1 de ACK.

## 3. Mapa de estados de um stream duplex

```
                open_stream(O)                 START_STREAM(B)
   [none] ─────────────────────> [opened] ──────────────────────> [streaming]
                                     │                                 │
                                     │ (credit=64 KiB)                 ├── read_credit>0 ──> pump lê destino ──> send_local_stream_event(DATA)
                                     │                                 │                                   │
                                     │                                 │      <── WINDOW_UPDATE(V) ────────┤ (limite 256 KiB)
                                     │                                 │
                                     │                                 ├── write_closed / half-close(H) ──> WRITE_EOF
                                     │                                 │
                                     │                                 └── remote EOF ──> EVENT(EOF) ──> read_chunk()==b""
                                     │
                                     └── CANCEL(X)/close ──> [closed]   (close_duplex_state: cancela pump, fecha destino)
```

Estados de circuito: `built` (guard+extend), `usable` (writer não fechado e budget de comandos não esgotado), `closing`, `closed`. O relay tem estados análogos por stream (`RelayDuplexState.read_credit`, `read_closed`, `write_closed`, `read_task`).

## 4. O que espera o quê (por mensagem)

| Mensagem | Espera resposta antes de prosseguir? | Onde | Pode ser independente? |
|---|---|---|---|
| `O` OPEN_STREAM | **sim** — `STREAM_OPENED` de todos os hops | `forward_duplex_command` → `forward_packet` (`:987`, `:956`) | Não: precisa do descritor/mapeamento antes de `START`. |
| `B` START_STREAM | **sim** — `STREAM_STARTED` | idem | Não: o `pump` do exit só começa depois. |
| `W` WRITE (duplex) | **sim por comando** — `WROTE+len`; até 4 em voo | `queue_forwarded_duplex_write` / `finish_local_write` | **Sim, em pipeline limitado**: comandos posteriores entram antes do ACK do anterior (ordem de sequência preservada). |
| `V` WINDOW_UPDATE | **sim** — `WINDOW_UPDATED` | `_flush_window_credit` (`:1816`) aguarda dentro de `read_chunk` | **Sim, com cuidado**: o ACK valida crédito, mas o relay já aplicou o crédito ao receber; o cliente pode continuar lendo enquanto o ACK viaja (variante D). |
| `H` HALF_CLOSE | **sim** — `WRITE_EOF` | `DuplexCircuitStream.write_eof` | Não: não pode ultrapassar `WRITE` em voo. |
| `X` CLOSE | **sim** — `STREAM_CLOSED` | `DuplexCircuitStream.close` | Não: encerra a contabilidade de crédito. |
| `EVENT(DATA)` (resposta) | **não** — eventos são unidirecionais, sequenciados por stream | `send_local_stream_event` (`:734`), `send_forwarded_stream_event` (`:743`) | Sim: cada hop sela e envia; o cliente valida sequência e remonta. |
| `EVENT(EOF)` | não | idem | Sim. |

**Conclusão estrutural**: o caminho de dados (eventos) já é independente e sequenciado; o que serializa são os **ACKs de controle por comando** (`WRITE`) e o **ACK de crédito** (`WINDOW_UPDATE`) — e, no caso one-shot, a resposta inteira de um hop.

## 5. As seis categorias de espera (separadas)

| # | Categoria | Onde é medida | O que é | Como o P2 mexe |
|---|---|---|---|---|
| 1 | RTT de controle | não instrumentado directamente; derivado de `downstream_response_wait` e do `setup_ms` | ida-e-volta de `O/B/V/W/X` por 3 hops | B/D (menos `V`), A (menos `V` por janela maior) |
| 2 | Espera de crédito | `flow_credit_wait` (relay) | `pump` bloqueado em `credit_condition.wait_for(read_credit>0)` (`:771`) | A (janela inicial), B (política de update) |
| 3 | Espera de leitura no destino | `destination_read_wait` | `reader.read(requested)` no exit | C (chunks maiores), parcialmente A/B (mais crédito → menos bloqueio) |
| 4 | Espera de ACK | `downstream_response_wait` (relay) | `await_downstream_response` (`:956`) — relay parado à espera do hop seguinte | D (ACK de crédito fora do caminho), C (menos eventos por comando) |
| 5 | AEAD e framing | `aead_*` (contadores do lab) | `seal`/`open_sealed` por hop e por evento + `frame()` | C (menos eventos ⇒ menos AEAD por byte) |
| 6 | Escalonamento | resíduo: parede − (1..5) | event loop, tasks, locks, cópias | nenhuma variante mexe; é o resíduo medido |

**Aviso de leitura (importante)**: `downstream_response_wait` e `flow_credit_wait` são **concorrentes** entre hops e entre streams. Somar as três cópias de relay como se fossem parcela do tempo de parede é errado; o P2 reporta os totais por relay *e* o parede do cliente, e trata a diferença como resíduo — nunca "soma = parede".

Evidência numérica da Fase 1 no caminho real (amostra única, `bulk_256k_c16k`, 3 hops, loopback): parede ≈ 120–170 ms; `flow_credit_wait` ≈ 0,1 ms (o crédito **não** domina este workload); `downstream_response_wait` é o estágio dominante; o número de `WINDOW_UPDATE` chega a ~1 por comando quando o intervalo entre chunks excede 2 ms (`duplex_4x128cmd`: 508 `V` para 512 comandos). Ou seja: o custo dominante no duplex não é o tamanho da janela, é **um RTT de controle por comando**.

## 6. Onde cada variante intervém

| Variante | Intervenção | Categoria alvo | Não altera |
|---|---|---|---|
| `control` | nenhuma | — | — |
| `credit-window-128k/256k` | `WINDOW_UPDATE` legal logo após `STREAM_STARTED` (crédito inicial efetivo maior, teto 256 KiB) | 2 | semântica de ACK, teto de crédito |
| `credit-policy-32k-1ms` / `128k-4ms` | limiar e prazo do *flush* de crédito | 2/1 | teto, autenticação |
| `credit-policy-window-aware` | só faz *flush* no prazo quando o crédito pendente pode deixar o relay sem janela (piso ≤ ½ janela) | 1 | teto, liveness (provado por invariante + teste) |
| `events-32k/64k` | leitura do destino e limite de evento do cliente | 3/4/5 | sequência, AEAD por evento, teto de buffer |
| `ack-pipeline` | ACK do `WINDOW_UPDATE` validado fora do caminho de leitura (single-flight, backlog limitado) | 4/1 | validação do ACK, crédito do relay |

## 7. O que esta auditoria **não** estabelece

- Não mede WAN, perda, jitter nem Tor; os valores absolutos são de loopback em um host.
- Não prova anonimato nem a meta de 90% da Surface (ver `06`/`10`).
- `downstream_response_wait` inclui espera do hop seguinte *e* do destino; a separação fina entre "ACK do hop" e "destino lento" só existe porque `destination_read_wait` é medido separadamente no exit.
- Os relays rodam no mesmo processo: CPU e escalonamento são compartilhados, então o estágio 6 é o menos atribuível do conjunto.

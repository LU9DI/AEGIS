# 09 — Perfil do custo de despacho no caminho AEGIS/THOR (P1, Fase 1)

- **Branch**: `perf/thor-dispatch-batching-lab` · **Base**: `b17b983b43fa48d614768110397a91f6c1bb8d7e`
- **Commit medido**: `bbb0e3f4affbe305cd10053e3b980021f5233c1d` (árvore limpa, `dirty: false` nos manifestos)
- **Artefato bruto**: `experiments/thor-dispatch-lab/profile-01.json` — 2 execuções por variante, 48 comandos de 64 KiB, lote de 4, 1 stream, métricas de relay ligadas.
- **Ambiente**: Windows 10.0.19045, Python 3.14.6, 4 vCPUs, `cryptography 50.0.2`, timer 1 ms, tudo em loopback no mesmo processo.
- **Instrumentação**: `src/anonlab/thor_lab/dispatch_profile.py` + `dispatch_lab.py`.

Nenhum número desta fase vem de outra fase: tudo foi medido nesta branch, no caminho real (relays reais, framing real, AEAD real).

## 1. Como o custo foi atribuído

1. **Contagem** (`count_primitives`): Futures criadas, `asyncio.wait_for`, `gather`, aquisições de lock e iterações do event loop — contagem direta.
2. **Preço** (`measure_primitive_costs`): custo medido de cada primitiva no mesmo run.
3. **AEAD real** (`count_aead_ops`): envolve `seal`/`open_sealed` nos módulos que os resolvem, contando chamadas e tempo dentro do caminho real (cliente **e** relays).
4. **Estágios de relay**: as métricas limitadas que o protótipo já expõe (`collect_relay_metrics`) e as métricas de lote do cliente (`collect_write_metrics`).

Resíduo explícito = parede − AEAD medido − primitivas calculadas.

## 2. Preço das primitivas neste host (duas execuções)

| Primitiva | Custo medido |
|---|---|
| Criar `Future` | 1,6–1,9 µs |
| `Future.set_result` | 0,6–0,7 µs |
| Adquirir/libertar `asyncio.Lock` | 3,1–3,3 µs |
| `asyncio.wait_for` sobre future resolvido (armar/desarmar timer) | **17,9–20,1 µs** |
| `asyncio.gather` de 2 futures resolvidos | 23,0–24,2 µs |
| `time.monotonic()` | 0,5 µs |

## 3. Primitive count por comando (controlo)

| Primitiva | Por comando |
|---|---|
| `Future`s criadas | 22,50 |
| `asyncio.wait_for` | 11,42 |
| `gather` | 0,29 |
| Aquisições de lock | 23,71 |
| Iterações do event loop | 15,29 |

Com os preços da §2: **0,32–0,36 ms por comando**, ou **~1,7–2,6% do tempo de parede**. As contagens são **idênticas** nas variantes (22,25–22,5 Futures, 11,42 `wait_for`, 23,71 locks, 15,29 iterações), porque a maior parte delas vem dos relays, não do cliente.

## 4. Onde o tempo realmente vai (controlo, duas execuções)

| Componente | Por comando | Fração do parede | Fração da CPU |
|---|---|---|---|
| Tempo de parede | 13,54–19,07 ms | 100% | — |
| CPU do processo (inclui os 3 relays) | 12,04–13,35 ms | 63–99% | 100% |
| **AEAD medido** (24 `seal` + 24 `open`) | **3,52–4,66 ms** | **~25%** | **26–39%** |
| Primitivas asyncio (calculado) | 0,32–0,36 ms | ~1,7–2,6% | ~2,5–2,7% |
| **Resíduo** (framing, cópias, tasks de relay, I/O, escalonamento) | **9,66–14,08 ms** | **~71–74%** | ~60–72% |

O número de operações AEAD por comando (24 `seal` + 24 `open`) é **4× o esperado para 3 hops** porque a resposta é fragmentada em eventos de 16 KiB (`STREAM_CHUNK_BYTES`): um comando de 64 KiB gera 4 eventos, cada um selado por hop e aberto pelo cliente. É custo de camada/protocolo, não de dispatcher.

### 4.1 O que o cliente observa por lote de 4 comandos (controlo)

| Fase do lote | Mediana (exec. 1 / exec. 2) | Por comando |
|---|---|---|
| Preparação de frames (inclui os seals do cliente) | 4,51 / 3,47 ms | 0,87–1,13 ms |
| **Espera de ACK (`response_wait`)** | **47,71 / 26,47 ms** | **6,6–11,9 ms** |
| `drain` de socket | 2,35 / 2,18 ms | 0,54–0,59 ms |
| Decodificação das respostas | 0,39 / 0,49 ms | 0,10–0,12 ms |
| Total do lote | 56,19 / 32,97 ms | — |

A espera de ACK é a maior parcela do parede e é gasta a aguardar o encadeamento de respostas dos 3 hops.

### 4.2 O que os relays reportam (execução 1, 303 amostras de dispatch)

| Estágio | Mediana | p95 | Total |
|---|---|---|---|
| `command_dispatch` | 0,44 ms | 16,21 ms | 1 149 ms |
| **`downstream_response_wait`** | **9,10 ms** | 30,60 ms | **2 426 ms** |
| `relay_reply_send` | 0,13 ms | 0,47 ms | 82 ms |
| `relay_event_send` | 0,03 ms | 1,64 ms | 187 ms |
| `flow_credit_wait` | 0,006 ms | 25,02 ms | **709 ms** |
| `destination_read_wait` | 0,016 ms | 0,045 ms | 69 ms |

O estágio dominante é `downstream_response_wait`: o relay passa a maior parte do tempo à espera do hop seguinte. `flow_credit_wait` acumula 709 ms em 193 amostras (p95 25,0 ms) — cada lote de crédito de leitura custa um round-trip de circuito.

## 5. Conclusão da Fase 1

> O gargalo **não** é a criação de Futures, os locks, os timers do `asyncio` nem a cópia de buffers no cliente: juntos são ~2–3% do tempo. O tempo é dominado por (a) AEAD real ~25% do parede (26–39% da CPU), amplificado 4× pela fragmentação da resposta em 16 KiB, e (b) **espera de ACK/resposta encadeada por hop**, 6,6–11,9 ms por comando, que nenhum batching do lado do cliente remove.

Consequência para a Fase 2: reduzir `write`s no cliente ataca uma parcela quase nula; reduzir dicionários/timers do cliente, outra parcela quase nula. O caminho com potencial estrutural é reduzir round-trips por comando (crédito/ACK no relay) ou mudar de transporte — fora do escopo desta fase.

## 6. Avisos de validade

- CPU é do processo e inclui os relays in-process.
- O perfilador mede uma transferência **duplex concorrente**; o benchmark oficial mede escrita-depois-leitura. As conclusões de cada modo estão separadas em `10`.
- Loopback: sem perda, sem RTT de rede, sem fila de pacotes; valores absolutos não são previsão de WAN.
- Host compartilhado (4 vCPUs, antivírus, daemon Tor noutro processo): duas execuções por variante; os valores variam entre execuções e são lidos como ordem de grandeza, não como constantes.

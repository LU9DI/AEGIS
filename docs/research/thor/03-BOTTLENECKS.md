# 03 — Gargalos prioritários

- **Fonte dos números**: `06-LAB-RESULTS.md` (`experiments/thor-lab/lab-01`, commit `1aa9130`), `07-PUBLIC-RESULTS.md`, `08-PROTOTYPE-RESULTS.md`.
- **Método**: decomposição medida, não opinião. No tier lab, origem, destino, payload e duração são idênticos entre braços; a diferença `surface` → `relay3_plain` isola o custo de topologia/saltos, e `relay3_plain` → `aegis_telescope3` isola cripto + despacho + framing.
- **Cuidado com ruído**: neste host de 4 vCPUs, o goodput absoluto da Surface variou até 2,3× entre blocos de workload da *mesma* execução. Por isso o gate usa ratios pareados por trial (com IC) e nenhuma conclusão abaixo depende de uma diferença absoluta isolada.

## 1. Decomposição medida do custo

| Carga | Surface (Mb/s) | relay3 (Mb/s) | AEGIS (Mb/s) | Fator topologia | Fator cripto+dispatch | Total |
|---|---|---|---|---|---|---|
| 256 KiB, comando 16 KiB | 109,14 | 90,80 | 21,90 | 1,20× | 4,15× | 4,98× |
| 256 KiB, comando 64 KiB | 253,04 | 94,33 | 35,32 | 2,68× | 2,67× | 7,16× |
| 256 KiB, comando 256 KiB | 236,40 | 105,21 | 37,77 | 2,25× | 2,79× | 6,26× |
| 1 MiB, comando 16 KiB | 211,90 | 98,64 | 18,84 | 2,15× | 5,24× | 11,25× |
| 8 streams × 64 KiB | 98,26 | 47,06 | 10,35 | 2,09× | 4,55× | 9,49× |
| RTT 1 KiB × 50 | 7,41 | 2,91 | 1,31 | 2,55× | 2,22× | 5,65× |
| metro 256 KiB, comando 16 KiB | 62,65 | 54,28 | 9,95 | 1,15× | 5,45× | 6,29× |
| metro 256 KiB, comando 64 KiB | 67,02 | 53,74 | 18,44 | 1,25× | 2,91× | 3,64× |
| metro RTT 1 KiB × 20 | 0,59 | 0,56 | 0,43 | 1,05× | 1,30× | 1,37× |

**Conclusão 1**: a topologia de 3 saltos custa ~1,2–2,7×; a camada de anonimato do AEGIS custa outros ~2,2–5,2× em cima disso; o fator total é **5,0–11,3×**. A meta de 90% exige fator ≤1,11×, ou seja, o protótipo precisa ser **~4,5–10× mais rápido** para atingir a meta, e **~2–4,5× mais rápido** para apenas empatar com uma cadeia TCP pura de 3 saltos.

O padrão se repete no tier emulado: quando o RTT do enlace domina (RTT de 1 KiB no metro), o AEGIS fica em 73% da Surface (fator 1,37×); quando é volume, o fator sobe para 3,6–6,3×. **O problema do AEGIS é CPU/despacho, não latência de rede.**

## 2. Onde o tempo realmente vai (e onde não vai)

Microbenchmark do caminho quente (`08`, `experiments/thor-lab/fastpath-01.json`): custo de 1 comando por hop em CPython puro, sem event loop:

| Tamanho | Custo de 1 comando/hop | Teto de goodput em cadeia serial de 3 hops | Goodput medido do AEGIS |
|---|---|---|---|
| 1 KiB | 13,1 µs | **208 Mb/s** | 1,31 Mb/s (round-trip, não comparável) |
| 16 KiB | 83,4 µs | **524 Mb/s** | 21,9 Mb/s |
| 256 KiB | 1,09 ms | **640 Mb/s** | 37,8 Mb/s |

Para volume, o teto imposto por cripto + cópias + framing é **14–34× maior** que o goodput medido. Isso é a evidência decisiva desta fase:

> **O gargalo não é AEAD, não é o tamanho do frame e não é a cópia do corpo. É o escalonamento e o despacho por comando no `asyncio` (uma `Future`, um lock, um timer e um round-trip por comando), somado ao tamanho de comando usado.**

Micro-custos medidos, em fração do comando de 1 hop:

| Item | 1 KiB | 16 KiB | 256 KiB | Veredito |
|---|---|---|---|---|
| Construção de objeto AEAD | 3,7 µs (~28%) | 3,7 µs (~4,4%) | 3,7 µs (~0,3%) | só importa em mensagem minúscula |
| Cache de AAD | 0,1–0,4 µs | ~0,0 µs | ~0,0 µs | irrelevante |
| Cópia do corpo (`bytes` slice) | 1,1 µs (~8%) | 2,9 µs (~3,5%) | 15,2 µs (~1,4%) | pequeno; `memoryview` remove quase toda a cópia |
| `frame()` concatenando header+payload | 1,7 µs | 3,2 µs (~3,8%) | 16,3 µs (~1,5%) | pequeno |
| Dict de despacho criado por comando | 1,0–2,1 µs (~8–16%) | ~2,1 µs (~2,5%) | ~1,0 µs (~0,1%) | barato de corrigir, mas não move a meta |
| **Soma dos micro-itens** | **~40%** | **~14%** | **~3%** | **não é o que separa o AEGIS dos 90%** |

## 3. Ranking dos gargalos

**B1 — Despacho por comando no event loop (dominante).** Evidência: teto micro 14–34× acima do medido; `handle` do relay já era 26,1% do cProfile do repositório (`experiments/cprofile-after-cache-v0.18.0.txt:14`). Por comando: uma `Future` de correlação, um lock de escrita, um `asyncio.wait_for` (timer), empacotamento da resposta e propagação de ACK — nada disso é criptografia. **Ação**: protótipo de transporte fora do `asyncio` (Rust/tokio ou despacho em lote), com critérios em `08` §5.

**B2 — Tamanho de comando (segundo maior, e o mais barato de corrigir).** Evidência medida (mesmo payload de 256 KiB, só o chunk muda): AEGIS 21,90 → 35,32 → 37,77 Mb/s (**+72%**); TTFB 62,25 → 26,38 → 22,51 ms (**−64%**). O protocolo já permite até `STREAM_WRITE_MAX_BYTES = 256 KiB` por comando e 4 MiB por batch (`telescoping.py:109-112`); o limite era a escolha de chunk do cliente/benchmark. **Ação**: adotar 64–256 KiB como chunk padrão para transferência em massa, documentando o trade-off (menos round-trips, rajadas maiores).

**B3 — Contenção e custo de estabelecimento sob múltiplas streams.** Evidência: 8 streams × 64 KiB → AEGIS 10,35 Mb/s vs 98,26 da Surface (0,107); `setup_ms` p50 229,07 ms para abrir 8 circuitos concorrentes, contra 6,79 ms da Surface. Um único circuito de 3 hops custa 25,5–30,4 ms (loopback), contra 1,4–2,1 ms de TCP direto — 15–20× mais caro de estabelecer, mas 8–16× mais barato que o estabelecimento Tor real medido (330–420 ms, `07`).

**B4 — Overhead de controle em mensagens pequenas.** Evidência: 1 KiB → `wire_down_ratio = 1,350` (35% de bytes extras na resposta) e `wire_up_ratio = 1,181`; em volume (256 KiB+) cai para 1,4–2,7%. O problema de banda é de mensagens pequenas, não de transferências grandes.

**B5 — Sem controle de congestionamento nem pacing próprios (estrutural).** Não medido por falta de modelo de perda no shaper; é o que impede negociar forma de rajada vs latência e o que torna o AEGIS incompatível com o modelo de padding/cover que o Tor usa.

**B6 — Memória não é o gargalo hoje.** RSS pico 49,3 MiB (lab), 40,6 MiB (emulado), 33,1 MiB (público), estável entre braços. A lista de observações por relay e o guard de replay sem evicção (`01` F4) são dívida latente, não o gargalo atual.

**B7 — Transporte loopback-only (bloqueio de avaliação).** Sem resolver F7 (`01`), não há número em WAN e a meta de 90% não pode ser avaliada em rede real.

## 4. Prioridade de execução

| Prioridade | Ação | Por que | Critério de aceitação |
|---|---|---|---|
| **P0** | Chunk padrão de 64–256 KiB para volume + medir TTFB | +72% de goodput e −64% de TTFB sem mudar bytes de protocolo nem privacidade | AEGIS ≥ 35 Mb/s em 256 KiB no lab (já observado: 35,3–37,8) |
| **P1** | Transporte fora do `asyncio` (Rust/tokio ou despacho em lote) | único caminho para atacar o fator 14–34× | reduzir cripto+dispatch de 2,2–5,2× para <1,2× mantendo o modelo de ameaça |
| **P2** | ACK/window-update agregados | atacar os 18–35% de overhead em mensagens pequenas | overhead de 1 KiB <10% sem perda de integridade nem deadlock em stream esparso |
| **P3** | Padding/cover com contabilidade de custo | requisito de privacidade, não de desempenho | TPR@FPR de WF cai com custo de banda declarado (`04` §5) |
| **P4** | Rust para caminho de pacotes (GSO/zerocopy) | só depois de P1 | protótipo medido em Linux com Shadow ou host real |

## 5. Hipóteses falsificáveis

1. **H1**: mover o despacho de comando para fora do `asyncio` eleva o goodput do AEGIS em ≥2× no lab com a mesma configuração. Falsificação: ganho <20% ou regressão de latência p95 de round-trip.
2. **H2**: o overhead de 35% em mensagens de 1 KiB é majoritariamente ACK/window-update, e ACK agregado o reduz a <10%. Falsificação: overhead não cai, ou cai com perda de integridade/deadlock.
3. **H3**: 256 KiB por comando é o ótimo até `MAX_PIPELINED_WRITE_PAYLOAD_BYTES`; acima disso o ganho satura. Falsificação: 512 KiB–1 MiB melhora >10% adicional.
4. **H4**: o custo de estabelecimento (25–30 ms) é dominado pelo handshake ntor + Ed25519, não pelo event loop. Falsificação: perfil de `connect_guard`+`extend` mostra outra distribuição.

## 6. O que não foi feito e por quê

- **Nenhuma micro-otimização foi integrada.** Cada uma vale ≤3,8% do custo por comando em volume, abaixo da resolução das comparações end-to-end; integrar sem demonstrar benefício violaria a regra da missão. A medição e a decisão estão em `08`.
- **Nenhum protótipo em Rust foi escrito.** Esta máquina não tem `rustc`/`cargo` (verificado com `Get-Command`); protótipo não compilado não é evidência. Desenho e critérios em `08` §5.
- **Perda de pacotes não foi simulada.** O shaper não modela perda (`network_impairment.py:1-7`); declarar resistência sem modelo seria fabricação.

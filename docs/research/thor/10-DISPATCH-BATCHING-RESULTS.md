# 10 — Batching e despacho: resultados e decisão (P1, Fases 2–4)

- **Branch**: `perf/thor-dispatch-batching-lab` · **Base**: `b17b983b43fa48d614768110397a91f6c1bb8d7e`
- **Código medido**: `592132bc37a6421ba504f8a36310bf8dd7fd58b1` (variantes) e `0217dd06d9a79aeaa6fedc67dad05729d82cdd44` (perfilador)
- **Commit de medição**: `bbb0e3f4affbe305cd10053e3b980021f5233c1d`, árvore limpa (`dirty: false`), 0 erros e 0 falhas de integridade nos 192 + 88 registos das duas campanhas.
- **Artefatos**: `experiments/thor-dispatch-lab/campaign-01/`, `ab-io-batch-01/`, `soak-01.json`, `profile-01.json` (Fase 1, ver `09`).

## 1. Variantes implementadas

| Nome | O que muda | O que **não** muda |
|---|---|---|
| `control` | nada (caminho atual) | — |
| `io_batch` | lote inteiro num único `write` + um `drain` | frames, AEAD, sequências, ACKs, admissão |
| `lean_dispatch` | sem dicionários por comando; sequências derivadas aritmeticamente; AAD público cacheado por circuito | idem |
| `combined` | ambos | idem |

Ativação só por configuração de laboratório (braços `aegis_io_batch`, `aegis_lean_dispatch`, `aegis_combined`). Nenhuma alteração em `telescoping.py`, `onion_protocol.py` ou nos relays; revisão em `11`.

## 2. Resultados oficiais — `campaign-01` (7 trials, ordem intercalada)

Razões pareadas por trial, variante/controlo (mediana · nº de trials em que a variante foi mais rápida):

| Workload | `io_batch` | `lean_dispatch` | `combined` |
|---|---|---|---|
| 1 MiB, chunks 16 KiB | 1,021 · 4/7 | 1,020 · 4/7 | 0,887 · 2/7 |
| 256 KiB, chunks 16 KiB | 1,095 · 4/7 | 1,058 · 5/7 | 1,100 · 5/7 |
| 256 KiB, chunks 256 KiB | 1,063 · 4/7 | 1,060 · 4/7 | 0,956 · 3/7 |
| 8 streams × 64 KiB | 1,030 · 5/7 | 1,063 · 5/7 | 1,045 · 4/7 |

Goodput absoluto (mediana, Mb/s) e razão contra a Surface:

| Workload | Surface | relay3 | controlo | io_batch | lean | combined |
|---|---|---|---|---|---|---|
| 1 MiB | 312,42 | 147,83 | 37,36 | 35,00 | 33,65 | 33,14 |
| 256 KiB @16K | 247,04 | 111,49 | 33,62 | 34,85 | 36,56 | 36,97 |
| 256 KiB @256K | 406,02 | 132,32 | 56,64 | 49,43 | 56,86 | 50,05 |
| 8 streams | 115,06 | 59,50 | 13,64 | 14,03 | 14,46 | 14,70 |

Gate de 90% (`candidato/surface ≥ 0,90`): **nenhum braço chega perto** — razões entre 0,082 e 0,152. **A meta de 90% continua não atingida**, e esta fase não a altera.

## 3. A/B focado, 20 trials pareados (`ab-io-batch-01`)

| Workload | Mediana pareada | Intervalo | Trials em que `io_batch` > controlo |
|---|---|---|---|
| 1 MiB | **1,004** | 0,831 – 1,605 | 10/20 |
| 256 KiB @16K | **1,047** | 0,815 – 1,559 | 11/20 |

Teste de sinal: 10/20 (p ≈ 1,00) e 11/20 (p ≈ 0,82) — **nenhum efeito detectável**. O sinal de +12% observado numa campanha exploratória anterior (árvore suja, descartada) não se reproduz.

## 4. Por que o cliente não é o gargalo (Fase 1)

Do `profile-01.json` (detalhe em `09`), no caminho real:

- **AEAD ~25% do parede** (26–39% da CPU); 24 `seal` + 24 `open` por comando de 64 KiB por causa da fragmentação da resposta em 16 KiB.
- **Primitivas asyncio ~2–3%** (22,5 Futures, 11,4 `wait_for`, 23,7 locks, 15,3 iterações do loop por comando) — **idênticas** entre controlo e variantes.
- **~71–74% de resíduo**, dominado por espera encadeada: `downstream_response_wait` mediano de 9,1 ms por hop e `response_wait` de 6,6–11,9 ms por comando no cliente; `flow_credit_wait` acumulou 709 ms num transfer de 48 comandos.

`io_batch` reduz `write`s do cliente — uma parcela de ~1% do tempo; `lean_dispatch` reduz outra parcela da mesma ordem. Era previsível que o ganho no workload oficial fosse nulo ou instável, e foi o que a medição mostrou.

## 5. Carga duplex concorrente (fora do workload oficial)

No perfilador, com escritor e leitor em paralelo (4 streams × 128 comandos, `soak-01.json`):

| Variante | Goodput | Parede/comando | CPU/comando | Integridade |
|---|---|---|---|---|
| controlo | 48,07 Mb/s | 10,9 ms | 10,0 ms | ok |
| combined | **50,77 Mb/s (+5,6%)** | 10,3 ms | 10,0 ms | ok |

Ao longo de três execuções (duas exploratórias descartadas e esta), o efeito duplex variou entre **+42%, −22% e +5,6%**. Conclusão honesta: **não é reproduzível neste host** e não sustenta nenhuma hipótese de ganho.

## 6. Decisão por variante

| Variante | Goodput reproduzível? | Custo de despacho reduzido? | Integridade/isolamento | Decisão |
|---|---|---|---|---|
| `io_batch` | não (0,89–1,10; A/B 1,00–1,05 com 10–11/20) | sim, mas sobre ~1% do custo | 30 testes passam | **Rejeitar para adoção** |
| `lean_dispatch` | não (1,02–1,06, sinais 4–5/7) | não (CPU igual ou maior; primitivas idênticas) | passam | **Rejeitar** |
| `combined` | não (0,89–1,10; inversões) | só parcelas marginais | passam | **Rejeitar para adoção** |

Nenhuma variante entra no caminho predefinido; `aegis_telescope3` continua a ser o único braço AEGIS usado por omissão. O resultado negativo está registado como resultado.

## 7. O que a medição indica como próximo alvo

Com ~71–74% do tempo em espera encadeada e fragmentação de resposta:

1. **Crédito de leitura e ACK no relay** (não no cliente): janela de 64 KiB com flush de 2 ms, cada flush custa um round-trip; `flow_credit_wait` acumulou 709 ms (p95 25 ms). Critério: reduzir `downstream_response_wait` e `flow_credit_wait` ≥50% sem alterar isolamento nem admissão.
2. **Eventos de resposta maiores que 16 KiB** (`STREAM_CHUNK_BYTES`): cada 16 KiB de resposta paga 3 `seal` + 3 `open`; agregar reduziria AEAD e framing por um fator até 4. Critério: medir goodput, latência de cauda e memória por stream com o limite de janela atual.
3. **Transporte** (Tokio/Rust) só depois de 1–2 e justificado por estes números. Esta fase não iniciou essa migração.

## 8. Limitações

- Loopback, um host, sem perda, sem WAN; nenhum número é previsão de Internet.
- Workload oficial escreve e depois lê; o resultado negativo vale para ele. Carga duplex tem evidência contraditória e insuficiente (§5).
- 7 trials no campaign e 20 no A/B: suficiente para rejeitar ganhos grandes; insuficiente para certificar ganhos de ~5%.
- CPU inclui os relays in-process.
- Nenhuma avaliação de anonimato; `11` cobre apenas regressões de isolamento, autenticação e limites.

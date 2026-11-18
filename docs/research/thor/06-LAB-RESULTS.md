# 06 — Resultados medidos: tier lab (e sensibilidade emulada)

- **Artefato bruto**: `experiments/thor-lab/lab-01/` (`trials.jsonl` com 144 registros, `manifest.json`, `summary.json`, `REPORT.md`).
- **Revisão do código**: `1aa9130539a30c7ab7c62f116b4fa8771709c584` (`dirty: false` no manifesto).
- **SHA-256 de `trials.jsonl`**: `88220ea1f296d89e276b5e110e5d4cbe4a58adeac3212c1af30910b9d11246b6`.
- **Ambiente**: Windows 10 (10.0.19045), Python 3.14.6, 4 CPUs lógicas, cryptography 50.0.2, resolução de timer elevada para 1 ms, seed `20261118`.
- **Validade**: 7 trials por combinação + 1 warmup por braço; 0 erros, 0 falhas de integridade nas 144 execuções.
- **O que este tier NÃO é**: não é WAN, não é Tor, não é prova de anonimato. Todos os sockets são IPv4 loopback no mesmo processo.

## 1. Gate da meta (goodput ≥ 90% da Surface), tier lab

| Workload | Candidato | Trials pareados | Ratio (mediana [IC 95%]) | Precisa de | Status |
|---|---|---|---|---|---|
| `bulk_echo:1048576x1@c16384i4` | `aegis_telescope3` | 7 | 0,100 [0,088; 0,112] | 9,03× | **não atingido** |
| `bulk_echo:1048576x1@c16384i4` | `relay3_plain` | 7 | 0,465 [0,370; 0,485] | 1,94× | não atingido |
| `bulk_echo:262144x1@c16384i4` | `aegis_telescope3` | 7 | 0,173 [0,144; 0,450] | 5,20× | não atingido |
| `bulk_echo:262144x1@c16384i4` | `relay3_plain` | 7 | 0,832 [0,460; 1,174] | 1,08× | não atingido |
| `bulk_echo:262144x1@c65536i4` | `aegis_telescope3` | 7 | 0,147 [0,124; 0,163] | 6,10× | não atingido |
| `bulk_echo:262144x1@c262144i4` | `aegis_telescope3` | 7 | 0,160 [0,141; 0,176] | 5,64× | não atingido |
| `parallel_bulk:8x65536@c16384i4` | `aegis_telescope3` | 7 | 0,107 [0,073; 0,125] | 8,58× | não atingido |
| `small_rtt:1024x50@c16384i4` | `aegis_telescope3` | 7 | 0,215 [0,151; 0,262] | 4,20× | não atingido |

Nenhum workload atinge 90%. O melhor caso é 21,5% (round-trip de 1 KiB) e o pior é 10,0% (1 MiB). **A meta de desempenho não está atingida no tier lab** — e o tier lab é o caso *mais favorável* possível (mesma máquina, sem rede).

## 2. Métricas completas por braço

### 256 KiB, comando de 16 KiB (`bulk_echo:262144x1@c16384i4`)

| Braço | n | Goodput Mb/s (p50) | TTFB ms | Conclusão p95 ms | p99 ms | Setup ms | Fio ↑ | Fio ↓ | CPU (1 núcleo) | RSS pico MiB |
|---|---|---|---|---|---|---|---|---|---|---|
| `surface` | 7 | 109,14 | 17,19 | 81,54 | 87,75 | 2,13 | 1,000 | 1,000 | 0,889 | 48,1 |
| `relay3_plain` | 7 | 90,80 | 22,42 | 75,61 | 89,72 | 3,05 | 1,000 | 1,000 | 0,901 | 48,1 |
| `aegis_telescope3` | 7 | 21,90 | 62,25 | 138,54 | 140,30 | 25,80 | 1,017 | 1,027 | 0,843 | 48,1 |

### 1 MiB, comando de 16 KiB

| Braço | n | Goodput Mb/s | TTFB ms | p95 ms | Setup ms | Fio ↑ | Fio ↓ | CPU | RSS MiB |
|---|---|---|---|---|---|---|---|---|---|
| `surface` | 7 | 211,90 | 29,93 | 55,83 | 1,58 | 1,000 | 1,000 | 0,747 | 48,1 |
| `relay3_plain` | 7 | 98,64 | 54,51 | 153,09 | 1,69 | 1,000 | 1,000 | 0,668 | 48,1 |
| `aegis_telescope3` | 7 | 18,84 | 250,54 | 550,70 | 28,57 | 1,014 | 1,024 | 0,663 | 48,1 |

### 1 KiB × 50 operações (`small_rtt:1024x50@c16384i4`)

| Braço | n | Goodput Mb/s | Latência p95 ms | Latência p99 ms | Conclusão p95 ms | Setup ms | Fio ↑ | Fio ↓ | CPU |
|---|---|---|---|---|---|---|---|---|---|
| `surface` | 7 | 7,41 | 2,53 | 4,22 | 129,20 | 1,48 | 1,000 | 1,000 | 0,835 |
| `relay3_plain` | 7 | 2,91 | 5,44 | 7,99 | 268,58 | 1,85 | 1,000 | 1,000 | 0,776 |
| `aegis_telescope3` | 7 | 1,31 | 9,39 | 10,45 | 442,44 | 30,36 | 1,181 | 1,350 | 0,900 |

### 8 streams × 64 KiB concorrentes (`parallel_bulk:8x65536@c16384i4`)

| Braço | n | Goodput agregado Mb/s | p95 ms | p99 ms | Setup por conexão ms |
|---|---|---|---|---|---|
| `surface` | 7 | 98,26 | 64,70 | 67,00 | 6,79 |
| `relay3_plain` | 7 | 47,06 | 179,31 | 184,91 | 7,65 |
| `aegis_telescope3` | 7 | 10,35 | 1 555,06 | 1 816,62 | 229,07 |

## 3. Resultado central: o tamanho de comando move mais que qualquer micro-otimização

Mesmo payload (256 KiB), apenas o chunk de escrita do cliente mudou:

| Chunk | AEGIS goodput Mb/s | AEGIS TTFB ms | Surface goodput Mb/s | Relay3 goodput Mb/s |
|---|---|---|---|---|
| 16 KiB | 21,90 | 62,25 | 109,14 | 90,80 |
| 64 KiB | 35,32 (+61%) | 26,38 (−58%) | 253,04 | 94,33 |
| 256 KiB | 37,77 (+72%) | 22,51 (−64%) | 236,40 | 105,21 |

O ganho do AEGIS é grande e na direção certa, mas **não fecha a meta**: mesmo com 256 KiB por comando, o AEGIS entrega 16% da Surface nesta execução. Note que o `surface` também varia entre os blocos (109 → 253 → 236 Mb/s), o que mostra o ruído do host; por isso o gate usa ratios pareados por trial, e não médias de blocos diferentes.

## 4. Overhead de banda: o problema é mensagem pequena, não volume

- Volume (256 KiB–1 MiB): `wire_up_ratio` 1,007–1,017 e `wire_down_ratio` 1,017–1,027 — **1–3% de overhead**. O AEAD e o framing não são um problema de banda.
- Round-trip de 1 KiB: `wire_up_ratio` 1,181 e `wire_down_ratio` 1,350 — **18% e 35%**. Aqui o custo é ACK de escrita + window update + cabeçalhos de evento por mensagem.

## 5. CPU e memória

- CPU por Mbit útil (fração de núcleo ÷ goodput p50, aproximado): AEGIS ≈ 0,017–0,039 core·s/Mb; Surface ≈ 0,0035–0,0047 core·s/Mb. **O caminho do AEGIS custa ~3,6× a ~10× mais CPU por bit útil**, já incluindo os 3 relays in-process. Isso é o custo total do caminho, não o custo do cliente.
- RSS: pico de 48,1 MiB para *todos* os braços — os relays vivem no mesmo processo, então a memória não discrimina os braços nesta configuração. As dívidas de memória do protótipo (`01` F4) não aparecem em escala de laboratório.

## 6. Sensibilidade com enlace emulado (metro: 5 ms ± 1 ms, 200 Mb/s)

Artefato: `experiments/thor-lab/emulated-01/` (54 registros, SHA-256 de `trials.jsonl` no `summary.json`).

| Workload | Braço | Goodput Mb/s | TTFB ms | Latência p95 ms | Ratio vs Surface | Status do gate |
|---|---|---|---|---|---|---|
| 256 KiB @16K | `surface` | 62,65 | 21,08 | — | 1,000 | — |
| | `relay3_plain` | 54,28 | 22,55 | — | 0,913 [0,747; 0,988] | **atingido** |
| | `aegis_telescope3` | 9,95 | 127,29 | — | 0,159 [0,132; 0,218] | não atingido |
| 256 KiB @64K | `surface` | 67,02 | 20,13 | — | 1,000 | — |
| | `relay3_plain` | 53,74 | 25,76 | — | 0,916 [0,731; 1,022] | **atingido** |
| | `aegis_telescope3` | 18,44 | 35,21 | — | 0,266 [0,213; 0,313] | não atingido |
| 1 KiB × 20 | `surface` | 0,59 | — | 16,48 | 1,000 | — |
| | `relay3_plain` | 0,56 | — | 17,07 | 0,954 [0,919; 1,004] | **atingido** |
| | `aegis_telescope3` | 0,43 | — | 23,68 | 0,760 [0,696; 0,872] | não atingido |

Leitura honesta: com RTT de enlace de ~10–16 ms, a cadeia TCP sem criptografia chega a 91–95% da Surface (o RTT domina), enquanto o AEGIS fica em 16–27% no volume e 76% no round-trip curto. **O gargalo do AEGIS é de CPU/despacho, não de RTT**; quando o RTT é adicionado artificialmente, o AEGIS *melhora* em relação à Surface porque a Surface passa a esperar a rede como o AEGIS já esperava.

Aviso do próprio tier: o shaper modela atraso/taxa por chunk, sem perda, retransmissão ou fila (`network_impairment.py:1-7`). Os valores absolutos de latência (16–24 ms para um perfil de 10 ms ida-e-volta) incluem a granularidade do timer do SO e o custo do proxy de contagem; são sensibilidade, não previsão.

## 7. O que estes resultados provam e o que não provam

**Provam** (dentro do tier lab, para este commit, este host e estes parâmetros):
1. A meta de 90% não é atingida por um fator de ~5–9×, e a ordem de grandeza é estável entre cargas.
2. A decomposição do custo: topologia de 3 saltos ≈ 1,9–2,4×; cripto+despacho do AEGIS ≈ 3–4,5× adicionais.
3. Overhead de banda é 1–3% em volume e 18–35% em mensagens pequenas — não é a barreira principal.
4. Comandos maiores (256 KiB) melhoram o AEGIS em 72% e reduzem TTFB em 64%, sem tocar no protocolo.
5. A CPU por bit útil é 3,6–10× a da Surface.

**Não provam**: desempenho em WAN, desempenho com perda, desempenho do Tor (tier diferente), generalização para outro hardware ou para outra versão do protótipo, nem qualquer propriedade de anonimato. O AEGIS **não tem** número em caminho real porque o transporte é loopback-only (`01` F7).

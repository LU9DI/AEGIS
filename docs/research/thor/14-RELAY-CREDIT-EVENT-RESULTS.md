# 14 — Resultados: crédito de leitura, evento de resposta e pipeline de ACK (THOR P2, Fases 2 e 4)

- **Branch**: `perf/thor-relay-credit-event-lab` · **Base**: `baecf8375704ad58d544712a410de725b1689360`
- **Commit medido**: `8c35be6b7794e77117023cb779feae3424a3fabe` (árvore rastreada limpa; `dirty: false` no manifesto)
- **Artefatos brutos**: `experiments/thor-p2-lab/campaign-01/` (315 trials + manifesto com SHA-256) e `experiments/thor-p2-lab/soak-01/soak.json`
- **Ambiente**: Windows 10.0.19045, Python 3.14.6, 4 vCPUs, `cryptography 50.0.2`, relays e cliente no mesmo processo, tudo em loopback. Tier `loopback`.
- **Reprodução**:
  ```
  python -m anonlab.thor_p2_lab run --output experiments/thor-p2-lab/campaign-01
  python experiments/thor-p2-lab/analyze_campaign.py experiments/thor-p2-lab/campaign-01
  python experiments/thor-p2-lab/soak.py --seconds 120 --output experiments/thor-p2-lab/soak-01
  ```

## 1. Método pré-registrado

- 9 braços (control + 8 variantes), 5 workloads P0/P1, **1 warmup descartado + 7 trials válidos** por célula.
- A ordem dos braços **rotaciona por trial** (nenhum braço é sempre primeiro/último) e o **mesmo seed de payload** é usado por todos os braços dentro de um trial → comparação pareada.
- Cada trial reconstrói o testbed inteiro (relays, chaves, replay guards) e mede só a janela de transferência.
- Razões pareadas (variante ÷ control) com **IC 95% por bootstrap** (4000 reamostragens, seed fixo registrado).
- **Critério de aceitação (definido antes de medir)**: ganho reprodutível em ≥ 2 workloads (limite inferior do IC da razão de goodput > 1), **nenhuma** mediana de p95/p99 acima de 1,05 em nenhum workload, integridade 100%.
- Falhas são registradas, nunca substituídas por retry silencioso. **315 trials, 0 falhas, 0 timeouts.**

Workloads (bytes úteis idênticos em todos os braços): `bulk_1mib_c16k`, `bulk_256k_c16k`, `bulk_256k_c256k`, `parallel_8x64k` (8 streams × 64 KiB), `duplex_4x128cmd` (4 streams × 128 comandos de 4 KiB).

> **Interpretação do `duplex_4x128cmd`**: a definição de “4 × 128 comandos” não existia no repositório; adotamos 4 streams × 128 comandos de 4 KiB (512 KiB por stream). Está registrado em `WORKLOADS` e no manifesto.

## 2. Resultados principais (medianas de 7 trials pareados)

### 2.1 Onde o crédito e o ACK dominam: `duplex_4x128cmd`

| Braço | goodput Mb/s | down-wait ms | V (WINDOW_UPDATE) | AEAD/KiB |
|---|---|---|---|---|
| control | 6,20 | 9 687 | 508 | 7,512 |
| `credit-policy-window-aware` | **7,65** | **6 546** | **60** | **4,887** |
| `credit-window-256k` | 5,81 | 10 456 | 512 | 7,512 |
| `ack-pipeline` | 5,35 | 10 870 | 508 | 7,512 |

Pareado vs control: goodput **1,448 [1,158; 1,513]**, wall **0,690 [0,661; 0,863]**, `downstream_response_wait` **0,578 [0,569; 0,729]**, eventos por hop 516 (inalterado), **V 508 → 60 (8,5× menos)** e AEAD por KiB 7,51 → 4,89 (−35%). É o efeito mais forte do P2 e reproduz o achado da Fase 1: o custo era **um round-trip de controle por comando**, não a janela.

### 2.2 Janela inicial: `bulk_256k_c256k`

| Braço | goodput Mb/s | credit-wait ms | V | AEAD/KiB |
|---|---|---|---|---|
| control | 38,51 | 29,05 | 4 | 0,680 |
| `credit-window-256k` | **43,71** | **16,62** | 2 | 0,539 |
| `events-64k` | 41,22 | 28,85 | 4 | **0,398** |

Pareado: `credit-window-256k` goodput **1,322 [1,014; 1,501]**, credit-wait **0,496 [0,394; 0,667]**; `events-64k` corta eventos **17 → 5** e AEAD/KiB **0,680 → 0,398 (−41%)**, sem perda de integridade.

### 2.3 Onde a agregação de eventos não age

Em `bulk_1mib_c16k` e `bulk_256k_c16k` os comandos de 16 KiB fazem o destino devolver dados em pedaços de 16 KiB; o exit lê o que já chegou, então `events-64k` **não reduz eventos** (65 → 65) nem AEAD por KiB (1,787 → 1,764). Confirmado: o tamanho do evento é limitado pela **granularidade de chegada**, não pelo limite de leitura.

### 2.4 Pipeline de ACK: resultado negativo, com causa

`ack-pipeline` no `bulk_1mib_c16k`: goodput **0,866 [0,845; 0,877]** e V 33 → 63. Ao não bloquear no ACK, o leitor volta ao ramo de prazo de 2 ms mais vezes e emite **mais** `WINDOW_UPDATE` (cada um custa AEAD e um RTT). O pipeline puro, sem repensar a política de flush, **piora** o caminho. É a evidência de que a variante D, isolada, deve ser rejeitada.

## 3. Decisões (registro de aceitas e rejeitadas)

| Braço | Workloads com IC-low > 1 | p95 ≤ 1,05 em todos | p99 ≤ 1,05 em todos | Integridade | Decisão |
|---|---|---|---|---|---|
| `credit-window-128k` | 0/5 | não | não | sim | **Rejeitada** |
| `credit-window-256k` | 1/5 | não | não | sim | **Rejeitada** (ganho forte só em `c256k`) |
| `credit-policy-32k-1ms` | 0/5 | não | não | sim | **Rejeitada** |
| `credit-policy-128k-4ms` | 2/5 | não | não | sim | **Rejeitada** (credit-wait 406× em 1 MiB) |
| `events-32k` | 1/5 | não | não | sim | **Rejeitada** |
| `events-64k` | 1/5 | não | não | sim | **Rejeitada** (ganho de evento real, goodput não reprodutível em 2 workloads) |
| `credit-policy-window-aware` | **3/5** | **não** | **não** | sim | **Rejeitada pelo critério pré-registrado** |
| `ack-pipeline` | 0/5 | não | não | sim | **Rejeitada** (regressão medida) |

**Nenhuma variante foi aceita.** O caso mais próximo é `credit-policy-window-aware`:

| Workload | goodput (razão pareada) | p95 | p99 | down-wait |
|---|---|---|---|---|
| `bulk_1mib_c16k` | 1,263 [1,061; 1,545] | 1,001 [0,640; 1,094] | 0,602 [0,548; 1,399] | 0,991 |
| `bulk_256k_c16k` | 1,099 [0,903; 1,391] | **1,198 [0,854; 1,573]** | 1,181 [0,659; 1,627] | 0,966 |
| `bulk_256k_c256k` | 1,162 [0,864; 1,938] | 0,939 [0,683; 1,362] | 0,932 [0,552; 1,069] | 1,056 |
| `parallel_8x64k` | 1,308 [1,047; 1,468] | 0,844 [0,781; 0,972] | 0,911 [0,816; 0,960] | 0,929 |
| `duplex_4x128cmd` | 1,448 [1,158; 1,513] | 0,832 [0,755; 1,274] | 0,857 [0,741; 1,315] | 0,578 |

O único bloqueio é a **mediana** de p95 no `bulk_256k_c16k` (1,198), cujo IC [0,854; 1,573] **não** distingue de “sem mudança”. Ou seja: o critério congelado (mediana pontual ≤ 1,05) rejeitou um candidato com 4/5 ganhos e 3/5 IC-low > 1. **Não afrouxamos o critério depois de ver os dados**; a recomendação para o P3 é pré-registrar “regressão de p95 somente quando o IC-low > 1,05” e medir só os workloads onde a variante se aplica.

## 4. Soak curto (120 s, 166 trials intercalados, `bulk_1mib_c16k`)

| Braço | goodput mediana | drift (2ª metade/1ª) | TTFB | p99 | V | RSS início→fim | pico |
|---|---|---|---|---|---|---|---|
| control | 15,45 Mb/s | 1,044 | 5,60 ms | 12,92 ms | 63 | 36,3 → 50,5 MB | 52,7 MB |
| `credit-policy-window-aware` | **18,40 Mb/s** | **1,022** | 5,54 ms | 13,11 ms | **31** | 41,3 → 50,5 MB | 52,7 MB |

Integridade 100%, zero erros, sem deriva crescente. **Isto é um soak curto de 2 minutos em loopback**, não um teste de durabilidade: não cobre horas, perda de pacotes, reconexão de rede nem memória sob 128 streams.

## 5. Classificação honesta

**Confirmado (medido nesta branch, com IC):**
1. No duplex com comandos pequenos, o custo dominante é **1 RTT de controle por comando**; a política *window-aware* reduz `WINDOW_UPDATE` em 8,5×, `downstream_response_wait` em ~42% e melhora goodput em ~45% (pareado, IC > 1).
2. Em transferência de comando grande (`c256k`), janela inicial de 256 KiB reduz credit-wait ~50% e melhora goodput ~32% (IC-low 1,014).
3. Agregar eventos (64 KiB) corta eventos 17→5 e AEAD/KiB em 41% quando a chegada permite; quando o destino entrega em 16 KiB, não muda nada.
4. O pipeline puro do ACK de crédito, com a política de 2 ms, **piora** goodput em ~13% e dobra `WINDOW_UPDATE` — resultado negativo reproduzível.

**Hipótese (não confirmada):**
- Que a política *window-aware* generalize para WAN/emulação (não medido) e que o critério de p95 baseado em IC aprove a variante (não re-medido).
- Que combinar evento 64 KiB + janela 256 KiB + window-aware some ganhos (proibido combinar antes de medir cada um).

**Limitações do ambiente:**
- Loopback, um host, 4 vCPUs, relays no mesmo processo: CPU/escalonamento compartilhados; valores absolutos não são previsão de WAN.
- 7 trials por célula: ICs largos em métricas de cauda (p99 do `c256k` tem IC [0,552; 1,069]).
- Sem perda, jitter, fila ou RTT real; o tier `emulated`/`public` não foi executado.
- Soak de 2 minutos apenas.

**Ainda não demonstrado:**
- Anonimato ≥ Tor e desempenho ≥ 90% da Surface — **não avaliados aqui**; nenhum número deste relatório sustenta essas metas.
- Isolamento entre tenants (o protótipo não tem multi-tenancy).
- Crédito duplicado/fora de ordem **no fio** por cliente adversarial de socket (as garantias vêm do parser sequencial do relay + testes de cliente).
- Pico de memória sob 128 streams com janela de 256 KiB (apenas aritmética: 32 MiB por relay no pior caso teórico).

## 6. Recomendação

Não adotar nenhuma variante no caminho padrão nesta fase. Levar ao P3, com pré-registro próprio: (a) re-medir `credit-policy-window-aware` com o critério de p95 por IC e workloads onde ela se aplica; (b) medir `window-256k` + `events-64k` **separadamente** em comandos grandes; (c) testar cliente adversarial de socket para crédito fora de ordem e duplicado; (d) medir memória com 128 streams; (e) só então considerar combinações.

# MALEBOLGE v0.22.0 — WINDOW_UPDATE timer cross-profile sensitivity

Data: 2026-10-09

## Objetivo

Verificar se a tendência favorável ao temporizador de 5 ms observada na matriz `metro` se reproduz em perfis de rede com maior latência e restrição de vazão. O limiar de crédito permaneceu em 64 KiB, o escalonador padrão permaneceu ativo e os demais parâmetros de workload foram mantidos iguais entre condições dentro de cada perfil.

## Configuração

- Perfis de shaping local: `intercontinental` e `constrained`.
- Temporizadores: 0,5 ms, 2 ms (controle padrão) e 5 ms.
- Duas rodadas por temporizador e perfil: 12 execuções completas no total.
- Transferência bulk de 128 KiB; quatro requisições interativas de 128 bytes, separadas por 25 ms; fluxo tardio iniciado após 100 ms.
- Chunks de escrita de 8 KiB e profundidade de pipeline 2.
- Ordem do timer rotacionada por rodada; a semente configurada foi pareada entre temporizadores dentro de cada rodada. TCP/asyncio ainda introduzem variabilidade temporal, logo isso não garante traços idênticos.

## Resultados pareados contra 2 ms

Os deltas abaixo são medianas das variações percentuais pareadas entre rodadas; a contagem W/L indica quantas das duas rodadas favoreceram ou prejudicaram o candidato na métrica. Menor RTT e menor tempo de conclusão são melhores.

| Perfil | Timer | Vazão bulk | Conclusão bulk | RTT p95 inicial | RTT p95 tardio | WINDOW_UPDATE (delta) |
|---|---:|---:|---:|---:|---:|---:|
| intercontinental | 0.5 ms | +1.75% (2W/0L/0T) | -1.70% (2W/0L/0T) | -6.27% (1W/1L/0T) | -0.09% (1W/1L/0T) | -3.33% |
| intercontinental | 5 ms | +2.69% (2W/0L/0T) | -2.61% (2W/0L/0T) | -5.79% (1W/1L/0T) | -3.09% (2W/0L/0T) | +0.00% |
| constrained | 0.5 ms | +0.80% (2W/0L/0T) | -0.79% (2W/0L/0T) | -2.94% (2W/0L/0T) | +0.74% (0W/2L/0T) | +4.02% |
| constrained | 5 ms | +0.75% (2W/0L/0T) | -0.74% (2W/0L/0T) | -3.21% (2W/0L/0T) | +1.75% (0W/2L/0T) | -6.25% |

### Medianas absolutas

| Perfil | Timer | Vazão (Mbps) | Conclusão bulk (ms) | RTT p95 inicial (ms) | RTT p95 tardio (ms) | Atualizações |
|---|---:|---:|---:|---:|---:|---:|
| intercontinental | 0.5 ms | 0.497 | 2110.1 | 466.9 | 619.5 | 14 |
| intercontinental | 2 ms | 0.488 | 2146.8 | 500.6 | 620.2 | 14.5 |
| intercontinental | 5 ms | 0.502 | 2090.5 | 469.3 | 600.8 | 14.5 |
| constrained | 0.5 ms | 0.299 | 3511.4 | 814.7 | 1152.7 | 15.5 |
| constrained | 2 ms | 0.296 | 3539.8 | 840.5 | 1144.2 | 15 |
| constrained | 5 ms | 0.299 | 3513.0 | 812.3 | 1164.4 | 14 |

## Interpretação

- **Intercontinental:** 5 ms apresentou +2,69% de vazão e −2,61% de tempo de conclusão nas variações pareadas medianas. O RTT p95 tardio caiu 3,09%, mas houve apenas duas rodadas; o RTT p95 inicial teve uma rodada favorável e uma desfavorável.
- **Constrained:** 5 ms trouxe apenas +0,75% de vazão e −0,74% de tempo de conclusão. O RTT p95 tardio piorou 1,75% em ambas as rodadas, embora o RTT p95 inicial tenha melhorado em ambas. O número de `WINDOW_UPDATE` caiu 6,25% nas variações pareadas medianas.
- **0,5 ms:** não mostrou melhora universal. No perfil constrained, o RTT p95 tardio piorou nas duas rodadas; em intercontinental, esse indicador ficou praticamente neutro.
- O contador de pausas de crédito >1 ms permaneceu zero nessas execuções de 128 KiB, portanto não é informativo para distinguir os timers neste workload. Zero nesse contador não significa ausência de toda espera de controle de fluxo.

## Decisão

**Manter 2 ms como padrão.** O timer de 5 ms pode melhorar throughput em alguns perfis, mas não entrega ganho estável de latência interativa entre perfis. O timer de 0,5 ms tampouco apresenta benefício robusto. Não há evidência suficiente para alterar o padrão ou promover versão.

## Limitações e transparência

- Somente duas rodadas por timer e perfil; resultados exploratórios, sem inferência estatística forte.
- Cada RTT p95 deriva de quatro requisições por fluxo e, nessa amostra minúscula, é fortemente influenciado pelo maior RTT observado; não deve ser interpretado como estimativa estável de cauda.
- A bancada maior inicialmente tentada no perfil intercontinental excedeu o limite de execução e não produziu artefato utilizável; foi substituída pelos ensaios de 128 KiB documentados neste relatório. O conjunto de 12 execuções é completo e validado.
- Todos os ensaios usam relays, proxies e destino na mesma máquina por IPv4 loopback. O shaper modela bytes de um fluxo TCP, não perda de pacotes IP, retransmissões reais nem congestionamento de uma WAN.
- A telemetria acrescenta overhead e contém metadados temporais, ainda que não registre payload, endereços ou identificadores dos streams.

## Reprodução

A partir da raiz do projeto:

```bash
PYTHONPATH=src python -m anonlab.window_update_timer_benchmark --profile intercontinental --trials 2 --timer-values-ms 0.5 2 5 --batch-bytes 65536 --bulk-bytes 131072 --interactive-requests 4 --request-bytes 128 --request-gap-ms 25 --stagger-after-ms 100 --write-chunk-bytes 8192 --pipeline-depth 2 --seed 20261030 --output experiments/window-update-timer-intercontinental-v0.22.0.json
PYTHONPATH=src python -m anonlab.window_update_timer_benchmark --profile constrained --trials 2 --timer-values-ms 0.5 2 5 --batch-bytes 65536 --bulk-bytes 131072 --interactive-requests 4 --request-bytes 128 --request-gap-ms 25 --stagger-after-ms 100 --write-chunk-bytes 8192 --pipeline-depth 2 --seed 20261031 --output experiments/window-update-timer-constrained-v0.22.0.json
```

## Verificações registradas

- 6/6 execuções intercontinental e 6/6 constrained: integridade, observabilidade, limpeza, buffers de eventos limitados e configuração efetiva aprovadas.
- Em todas as 12 execuções, o fluxo tardio começou enquanto a transferência bulk ainda estava ativa.
- `unittest`: 154 testes passaram com `ResourceWarning` promovido a erro.
- `pytest`: 156 testes e 23 subtestes passaram.
- A versão do pacote permanece em `0.22.0`.

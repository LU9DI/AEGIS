# MALEBOLGE v0.22.0 — Sparse interactive `WINDOW_UPDATE` timer sensitivity

## Pergunta

O temporizador de 5 ms, que em um workload interativo frequente apresentou ganhos de vazão num perfil metro, continua vantajoso quando requisições pequenas chegam de forma esparsa, com 250 ms entre solicitações?

## Método

- Perfis: `metro` e `intercontinental`, executados através de proxies TCP locais por IPv4 loopback.
- Temporizadores: 2 ms (padrão/controle) e 5 ms (candidato); limiar de crédito fixado em 65.536 bytes (64 KiB).
- Repetições: quatro por temporizador e perfil; 16 execuções completas. A ordem dos temporizadores alterna por rodada.
- Cada ensaio: bulk de 128 KiB; quatro requisições interativas de 128 bytes, com **250 ms entre requisições**; fluxo tardio programado para começar 100 ms depois.
- Chunks de escrita de 8 KiB, pipeline de profundidade 2 e escalonador padrão.
- Sementes de shaping pareadas dentro da rodada; isso pareia entradas aleatórias configuradas, não os escalonamentos TCP/asyncio exatos.

## Resultados

Variações percentuais pareadas medianas de 5 ms em relação ao controle de 2 ms. Para latência/conclusão, valores positivos significam piora; para vazão, valores negativos significam piora.

| Perfil | Métrica | Mediana 2 ms | Mediana 5 ms | Delta pareado mediano | Rodadas favoráveis a 5 ms |
|---|---|---:|---:|---:|---:|
| metro | Vazão bulk (Mbps) | 2.493 | 2.398 | -7.80% | 0/4 (ganha/perde/empata: 0/4/0) |
| metro | Conclusão bulk (ms) | 420.543 | 437.280 | +8.66% | 0/4 (ganha/perde/empata: 0/4/0) |
| metro | RTT p95 inicial (ms) | 97.033 | 112.208 | +10.87% | 1/4 (ganha/perde/empata: 1/3/0) |
| metro | RTT p95 tardio (ms) | 72.406 | 75.928 | +4.71% | 0/4 (ganha/perde/empata: 0/4/0) |
| metro | Comandos `WINDOW_UPDATE` | 14.0 | 14.0 | +0.00% | contexto (0/0/4) |
| intercontinental | Vazão bulk (Mbps) | 0.541 | 0.528 | -1.05% | 1/4 (ganha/perde/empata: 1/3/0) |
| intercontinental | Conclusão bulk (ms) | 1938.522 | 1984.649 | +1.07% | 1/4 (ganha/perde/empata: 1/3/0) |
| intercontinental | RTT p95 inicial (ms) | 483.083 | 501.672 | +2.59% | 0/4 (ganha/perde/empata: 0/4/0) |
| intercontinental | RTT p95 tardio (ms) | 458.580 | 459.598 | +3.55% | 1/4 (ganha/perde/empata: 1/3/0) |
| intercontinental | Comandos `WINDOW_UPDATE` | 14.5 | 14.0 | -3.33% | contexto (0/0/2) |

### Interpretação

- **Metro:** a 5 ms, a vazão caiu 7,80% na mediana das variações pareadas e o tempo de conclusão aumentou 8,66%. O RTT p95 inicial piorou 10,87% e o RTT p95 tardio piorou 4,71%; nas quatro rodadas, o p95 tardio foi pior com 5 ms.
- **Intercontinental:** a 5 ms, a vazão caiu 1,05% e a conclusão piorou 1,07%. O RTT p95 inicial piorou 2,59% nas variações pareadas; o RTT p95 tardio piorou 3,55%.
- O número mediano de comandos `WINDOW_UPDATE` ficou igual no perfil metro e caiu 3,33% no intercontinental. Isso não compensou a piora de responsividade observada neste workload.
- Em todas as execuções, `flow_pause_over_1ms_count` foi zero; essa métrica, portanto, não discrimina os temporizadores neste tamanho de carga. Zero acima de 1 ms não significa ausência de toda espera de crédito.

**Decisão: manter 2 ms como padrão.** O temporizador de 5 ms não apresentou vantagem com tráfego interativo esparso. Esse resultado é compatível com o papel do temporizador como limite de espera para crédito abaixo do limiar, mas não demonstra sozinho uma explicação causal.

## Validação

- 16/16 execuções completas passaram pelas verificações do benchmark: integridade de payload, observabilidade dos relays, fechamento de recursos, limites do buffer de telemetria e parâmetros efetivos.
- Em 16/16 execuções, o fluxo tardio começou enquanto a transferência bulk ainda estava ativa.
- Dados agregados e dados por perfil foram gravados em JSON dentro de `experiments/`.
- A suíte completa de testes foi executada após a coleta; os resultados exatos estão em `experiments/VALIDATION_WINDOW_UPDATE_TIMER_SPARSE_INTERACTIVE_V0.22.0.md`.

## Limitações

- Quatro repetições por condição são exploratórias e insuficientes para conclusões inferenciais fortes.
- O p95 deriva de apenas quatro requisições interativas por execução e é especialmente sensível à maior observação.
- O benchmark roda em uma única máquina; os proxies moldam bytes do fluxo TCP, não perda IP, retransmissão ou congestionamento WAN real.
- Mesmo com sementes pareadas e ordem alternada, tempos de eventos, escalonamento do sistema operacional e sockets não são determinísticos.
- A telemetria adiciona overhead e registra metadados temporais, embora não grave payloads nem endereços.

## Reprodução

```bash
PYTHONPATH=src python -m anonlab.window_update_timer_benchmark --profile metro --trials 4 --timer-values-ms 2 5 --batch-bytes 65536 --bulk-bytes 131072 --interactive-requests 4 --request-bytes 128 --request-gap-ms 250 --stagger-after-ms 100 --write-chunk-bytes 8192 --pipeline-depth 2 --seed 20261041 --output experiments/window-update-timer-sparse-metro-v0.22.0.json
PYTHONPATH=src python -m anonlab.window_update_timer_benchmark --profile intercontinental --trials 4 --timer-values-ms 2 5 --batch-bytes 65536 --bulk-bytes 131072 --interactive-requests 4 --request-bytes 128 --request-gap-ms 250 --stagger-after-ms 100 --write-chunk-bytes 8192 --pipeline-depth 2 --seed 20261042 --output experiments/window-update-timer-sparse-intercontinental-v0.22.0.json
```

# Relatório de diagnóstico por relay — MALEBOLGE v0.22.0

## Objetivo e método

A instrumentação por relay foi adicionada para diferenciar espera pelo próximo salto, processamento da aplicação de saída e bloqueios de crédito de leitura. Foi usada a matriz A/B de cargas mistas com 3 trials por escalonador (6 execuções no total), perfil `metro`, circuito de 3 relays, transferência principal de 262.144 bytes, cinco requisições interativas por stream, espaçamento de 5 ms, chegada tardia após 20 ms, blocos de escrita de 16 KiB e pipeline de profundidade 4. A ordem de execução foi alternada e os seeds foram pareados por trial.

Todas as 6 execuções passaram nas verificações de integridade, observabilidade dos relays e encerramento dos recursos; em todas, o fluxo interativo tardio começou durante a transferência principal. As amostras são pequenas e exploratórias. Como a telemetria está ativada, os valores de tempo não devem ser comparados diretamente com benchmarks sem instrumentação.

## Resultado A/B resumido

Medianas observadas por condição; o delta é `round-robin / baseline - 1`. Para latência e conclusão, valores negativos seriam melhores.

| Métrica | Padrão | Round-robin | Delta |
|---|---:|---:|---:|
| bulk_goodput_mbps | 6.257 | 6.185 | -1.15% |
| bulk_time_to_first_byte_ms | 53.212 | 53.572 | +0.68% |
| bulk_completion_ms | 335.145 | 339.052 | +1.17% |
| early_interactive_rtt_p50_ms | 102.142 | 99.617 | -2.47% |
| early_interactive_rtt_p95_ms | 110.273 | 111.371 | +1.00% |
| late_interactive_rtt_p50_ms | 84.802 | 87.476 | +3.15% |
| late_interactive_rtt_p95_ms | 123.016 | 120.138 | -2.34% |
| late_interactive_completion_ms | 501.983 | 505.294 | +0.66% |

A responsividade é mista: o RTT p50 do fluxo tardio melhorou ou piorou dependendo da métrica, o RTT p95 do fluxo inicial subiu 1,00%, e o p95 do fluxo tardio caiu 2,34%. A vazão do fluxo grande caiu apenas 1,15% nesta amostra e seu tempo de conclusão aumentou 1,17%. Isso não demonstra um benefício consistente do round-robin e não justifica promovê-lo ao escalonador padrão.

## Temporização por hop

Os valores são agregados sobre as três execuções de cada condição. `total_ms` soma amostras concorrentes, portanto não representa tempo de parede do ensaio. `command_dispatch` pode incluir esperas assíncronas iniciadas pelo handler e **não é uma medição pura de CPU**.

| Condição | Hop | Estágio | Amostras | Mediana (ms) | p95 (ms) | Soma (ms) |
|---|---:|---|---:|---:|---:|---:|
| baseline | 1 | `command_dispatch` | 161 | 12.174 | 25.782 | 1918.7 |
| baseline | 1 | `downstream_response_wait` | 158 | 23.897 | 30.039 | 3851.4 |
| baseline | 1 | `relay_reply_send` | 161 | 0.017 | 0.035 | 3.3 |
| baseline | 1 | `relay_event_send` | 87 | 0.009 | 0.013 | 0.8 |
| baseline | 2 | `command_dispatch` | 158 | 9.448 | 12.774 | 932.6 |
| baseline | 2 | `downstream_response_wait` | 155 | 11.743 | 14.948 | 1856.0 |
| baseline | 2 | `relay_reply_send` | 158 | 0.020 | 0.038 | 4.2 |
| baseline | 2 | `relay_event_send` | 87 | 0.009 | 0.013 | 0.8 |
| baseline | 3 | `command_dispatch` | 155 | 0.023 | 0.376 | 9.7 |
| baseline | 3 | `flow_credit_wait` | 87 | 0.002 | 56.063 | 748.2 |
| baseline | 3 | `destination_read_wait` | 87 | 2.364 | 117.295 | 3447.4 |
| baseline | 3 | `destination_write_drain` | 78 | 0.001 | 0.001 | 0.1 |
| baseline | 3 | `relay_reply_send` | 155 | 0.014 | 0.023 | 2.2 |
| baseline | 3 | `relay_event_send` | 87 | 0.008 | 0.013 | 0.9 |
| round_robin | 1 | `command_dispatch` | 160 | 12.153 | 25.788 | 1883.7 |
| round_robin | 1 | `downstream_response_wait` | 157 | 23.834 | 30.346 | 3843.4 |
| round_robin | 1 | `relay_reply_send` | 160 | 0.016 | 0.035 | 3.1 |
| round_robin | 1 | `relay_event_send` | 87 | 0.009 | 0.013 | 0.8 |
| round_robin | 2 | `command_dispatch` | 157 | 9.211 | 12.918 | 927.0 |
| round_robin | 2 | `downstream_response_wait` | 154 | 11.867 | 15.345 | 1875.8 |
| round_robin | 2 | `relay_reply_send` | 157 | 0.020 | 0.037 | 3.1 |
| round_robin | 2 | `relay_event_send` | 87 | 0.009 | 0.013 | 0.8 |
| round_robin | 3 | `command_dispatch` | 154 | 0.024 | 0.394 | 8.5 |
| round_robin | 3 | `flow_credit_wait` | 87 | 0.002 | 67.570 | 839.8 |
| round_robin | 3 | `destination_read_wait` | 87 | 2.199 | 115.128 | 3484.9 |
| round_robin | 3 | `destination_write_drain` | 78 | 0.001 | 0.001 | 0.1 |
| round_robin | 3 | `relay_reply_send` | 154 | 0.014 | 0.032 | 2.4 |
| round_robin | 3 | `relay_event_send` | 87 | 0.008 | 0.014 | 0.7 |

### Controle de fluxo no relay de saída (hop 3)

| Métrica | Padrão | Round-robin |
|---|---:|---:|
| Amostras de espera por crédito | 87 | 87 |
| Pausas de pelo menos 1 ms | 15 | 15 |
| Soma das pausas acima do limite (ms) | 748.05 | 839.61 |
| Maior pausa observada (ms) | 72.68 | 93.47 |
| Comandos `window_update` | 41 | 40 |
| Comandos `write` | 78 | 78 |

O p95 das esperas por crédito do hop 3 foi 56.06 ms no padrão e 67.57 ms no round-robin. Existem pausas longas entre várias verificações imediatas; por isso a mediana é próxima de zero enquanto o p95 é alto. Isso identifica um alvo para uma próxima experiência de sensibilidade no tamanho da janela e no limiar de atualização de crédito. Os totais sobrepostos não devem ser interpretados como atraso serial acumulado.

O `downstream_response_wait` mediano foi 23.90 ms no hop 1 e 11.74 ms no hop 2 para a condição padrão. A escrita no destino local (`destination_write_drain`) ficou perto de 0,001 ms mediano, enquanto `destination_read_wait` inclui espera legítima até o endpoint echo produzir dados — não é CPU nem, isoladamente, um defeito do relay.

## Privacidade e segurança da instrumentação

A telemetria do relay é desativada por padrão e usa um buffer com limite de 8.192 eventos por relay. Eventos contêm somente estágio, categoria de operação e duração; não armazenam bytes de payload, IDs de stream, IDs de relay ou endereços. Os tempos e as categorias de operação ainda são metadados de tráfego sensíveis e podem revelar padrões de atividade.

## Validação

- `unittest`: 148 testes aprovados com `ResourceWarning` tratado como erro.
- `pytest`: 150 testes aprovados e 11 subtestes aprovados.
- Matriz A/B: 6/6 execuções passaram em integridade, observabilidade e limpeza; todos os fluxos tardios começaram com o fluxo grande ativo.
- Integridade de artefatos registrada em `MALEBOLGE-v0.22.0-relay-diagnostics-SHA256SUMS.txt`.

## Limitações e decisão

O experimento foi realizado em um host usando IPv4 loopback e proxies que moldam fluxos de bytes TCP. Não emula perda de pacotes IP nem retransmissões reais; não é uma medição WAN, uma prova de anonimato ou uma auditoria criptográfica. Mantenha o escalonador padrão inalterado. Próximo experimento recomendado: comparar limiares de `WINDOW_UPDATE` menores com o padrão de 64 KiB e verificar se as pausas de crédito diminuem sem gerar um excesso de comandos de controle.

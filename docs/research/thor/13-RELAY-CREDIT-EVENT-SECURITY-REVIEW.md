# 13 — Revisão de segurança das variantes de crédito, evento e ACK (THOR P2, Fase 3)

- **Branch**: `perf/thor-relay-credit-event-lab` · **Base**: `baecf8375704ad58d544712a410de725b1689360`
- **Escopo**: variantes de laboratório em `src/anonlab/thor_p2_lab/` e os knobs aditivos em `src/anonlab/telescoping.py`.
- **Tier**: `loopback` (um host, relays no mesmo processo). O adversário modelado aqui é **um peer/relay que se desvia do protocolo** (mensagens inválidas, crédito excessivo, eventos gigantes, flood), não um atacante de rede.
- **Testes**: `tests/test_thor_p2_lab.py` (32 testes) — executados nesta branch; resultado no relatório de resultados.

## 1. Invariantes que nenhuma variante pode quebrar

| Invariante | Onde vive | Como o P2 o preserva |
|---|---|---|
| AEAD por hop em cada comando e evento | `_seal_reply` / `open_sealed` | nenhuma variante toca chaves, nonces, AAD ou o número de camadas |
| Autenticação de link (Ed25519) no handshake | `_link_hello` / `_authenticate_relay_endpoint` | inalterada; nenhuma variante relaxa `authorized_peer_ids` |
| Sequência monotônica por stream e por hop | `_COMMAND_HEADER`, `next_event_sequence`, `_event_sequences` | eventos continuam sequenciados; o ACK do `WINDOW_UPDATE` continua correlacionado por `(sequência, stream)` |
| Teto de crédito por stream (256 KiB) | relay: `state.read_credit + amount > MAX_STREAM_WINDOW_BYTES` | relay recusa; testado com pedido único de 256 KiB sobre 64 KiB iniciais |
| Sem over-credit / sem crédito duplicado | relay (autoridade) + cliente (só devolve bytes consumidos) | `_flush_window_credit` só envia bytes já consumidos; backlog do pipeline é limitado e testado |
| Buffer de recepção limitado | `_accept_event`: `len(buffer) + len(payload) > MAX_STREAM_WINDOW_BYTES` | mantido; `max_event_bytes` limita **cada** evento e nunca excede a janela |
| ACK validado antes de prosseguir a contabilidade | `WROTE+len`, `WINDOW_UPDATED`, `STREAM_*` | pipeline muda **onde** se espera, não **se** se valida; ACK inválido → `_fail` + fecha o circuito |
| Backpressure sob consumidor lento | crédito de leitura (o exit para quando o crédito acaba) | nenhuma variante injeta crédito sem consumo correspondente |
| Falha fecha o circuito | `except` dos handlers + `close_duplex_state` | todas as variantes falham fechadas nos testes |

## 2. Análise por variante

### A. Janela de crédito (`credit-window-128k`, `credit-window-256k`)
- **Mudança**: um `WINDOW_UPDATE` legal logo após `STREAM_STARTED`, elevando o crédito total a 128/256 KiB.
- **Risco**: over-credit; memória do exit.
- **Mitigação**: o relay é a autoridade e recusa acima de `MAX_STREAM_WINDOW_BYTES` (`test_over_credit_is_rejected_by_the_relay`); o cliente só pede até o teto (validação em `VariantSpec`).
- **Risco residual**: o exit pode bufferizar até 256 KiB por stream antes de o cliente ler. O limite é o mesmo `MAX_STREAM_WINDOW_BYTES` já existente; com `MAX_ACTIVE_STREAMS = 128`, o pior caso teórico por relay é 128 × 256 KiB = 32 MiB — **não medido** nesta fase.

### B. Política de crédito (`32k-1ms`, `128k-4ms`, `window-aware`)
- **Mudança**: limiar/prazo do flush; em `window-aware`, o prazo só dispara quando o crédito pendente pode deixar o relay sem janela (`floor ≤ window/2`).
- **Risco (crítico)**: starvation/deadlock — se o cliente deixar de devolver crédito, o exit bloqueia e a leitura trava para sempre.
- **Mitigação**: invariante de liveness: no ramo de espera o buffer está vazio, então o relay detém `window − pending`; com `floor ≤ window/2` e `chunk ≤ window/2`, o relay tem sempre ≥ 1 chunk de crédito, e o flush ocorre assim que `pending ≥ floor`. Provado no código e coberto por `test_cancel_during_credit_wait_returns_promptly`, `test_slow_consumer_backpressure_bounds_memory` e pela matriz de integridade (todos os workloads completam).
- **Risco residual**: a prova assume `relay_read_chunk_bytes ≤ window/2`; `VariantSpec` valida `max_event_bytes ≥ relay_read_chunk_bytes` e `floor ≤ window/2`, mas a combinação `chunk > window/2` com `window-aware` **não é permitida** pela validação do lab (documentado).

### C. Agregação de eventos (`events-32k`, `events-64k`)
- **Mudança**: o exit lê até 32/64 KiB do destino por evento; o cliente aceita eventos até esse tamanho.
- **Risco**: alocação forçada pelo peer (evento gigante), fragmentação de sequência, quebra de framing.
- **Mitigação**: `max_event_bytes` é limite **do cliente** (não do peer) e ≤ 256 KiB; `test_client_rejects_events_larger_than_its_bound` injeta um evento maior que o limite e exige falha fechada; `frame()`/`_seal_reply` mantêm os limites de frame; a sequência por hop é validada em `_accept_event`.
- **Risco residual**: eventos maiores aumentam a rajada observável no link (ver §4).

### D. Pipeline de ACK (`ack-pipeline`)
- **Mudança**: o ACK do `WINDOW_UPDATE` é validado por uma task single-flight; o leitor não bloqueia.
- **Risco**: ACK atrasado/duplicado aplicando crédito duas vezes; ACK perdido deixando crédito “fantasma”; corrida com `close()`.
- **Mitigação**: o relay aplica o crédito **uma vez** ao receber (autoridade), o cliente nunca reenvia o mesmo montante (backlog é consumido e zerado antes do envio), o ACK é validado (`WINDOW_UPDATED`) e qualquer falha → `_fail` + `client.close()`; `close()` cancela a task de crédito; `test_circuit_loss_during_pipelined_credit_fails_closed` e `test_window_update_flood_fails_closed_without_hanging` cobrem os extremos.
- **Risco residual**: com pipeline, o crédito é devolvido mais cedo — o exit pode ler mais cedo e bufferizar até a janela. O teto do relay não muda; o pico de memória não foi medido sob carga de 128 streams.

## 3. Matriz de testes de segurança

| Teste | Ameaça coberta |
|---|---|
| `test_over_credit_is_rejected_by_the_relay` | peer tenta elevar crédito acima do teto |
| `test_window_update_flood_fails_closed_without_hanging` | flood de `WINDOW_UPDATE` |
| `test_client_rejects_events_larger_than_its_bound` | evento gigante forçado pelo peer |
| `test_slow_consumer_backpressure_bounds_memory` | consumidor lento / buffer sem limite |
| `test_cancel_during_credit_wait_returns_promptly` | cancelamento durante espera de crédito |
| `test_circuit_loss_during_pipelined_credit_fails_closed` | falha de relay durante ACK pipelined |
| `test_variant_transfer_preserves_integrity_and_sequence` (9 variantes) | integridade, ordem e sequência por variante |
| `test_streams_do_not_leak_bytes_across_each_other` | isolamento entre streams |
| `test_half_close_is_preserved_under_variants` | EOF/half-close sob eventos maiores |
| `test_lab_knobs_default_to_production_values` | regressão silenciosa do caminho padrão |
| `test_relay_read_chunk_bounds_are_validated` | knobs fora de faixa |
| `test_unsafe_variant_knobs_are_rejected` (7 casos) | configurações perigosas |

**Limites explícitos desta revisão** (não demonstrar é diferente de negar):
- Não há teste de isolamento entre **tenants** porque o protótipo não tem multi-tenancy: os relays são por circuito e o lab não constrói um cenário de tenant compartilhado.
- Não há teste de crédito “fora de ordem” no fio: o parser do relay aplica comandos em ordem de sequência e rejeita sequência divergente; um teste que injete frames fora de ordem exigiria um cliente adversarial em nível de socket, não implementado nesta fase.
- Não há medição de pico de memória sob 128 streams com janela de 256 KiB; é uma extrapolação aritmética, não um resultado.
- Não há defesa de tráfego (padding, batching, timing) e nenhuma variante a introduz: a granularidade dos eventos continua observável no link de saída.

## 4. Efeitos de privacidade observáveis (o que o P2 mudou)

Eventos maiores (variante C) **reduzem o número de mensagens** e o AEAD por byte, o que remove alguma granularidade fina de temporização, mas **aumentam a rajada** por mensagem. Não medimos resistência a análise de tráfego; a conclusão honesta é que o P2 altera o perfil de rajada e não demonstrou nem ganho nem perda de anonimato. A meta de anonimato ≥ Tor **não** é avaliada aqui.

## 5. Veredito de segurança

Todas as variantes **falham fechadas** nos cenários testados: nenhum over-credit, nenhum buffer sem limite, nenhum dado cruzando streams, nenhuma remoção de ACK/autenticação. As mudanças são aditivas e o caminho padrão é idêntico (`test_lab_knobs_default_to_production_values`, suíte completa verde).

Isso **não** é uma auditoria criptográfica nem uma prova de anonimato; é evidência de que as variantes experimentais preservam os invariantes existentes sob os ataques testados.

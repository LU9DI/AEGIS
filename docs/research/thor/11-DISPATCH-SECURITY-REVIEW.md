# 11 — Revisão de segurança dos protótipos de dispatch (P1)

- **Branch**: `perf/thor-dispatch-batching-lab`
- **Base**: `b17b983b43fa48d614768110397a91f6c1bb8d7e`
- **Escopo revisado**: `src/anonlab/thor_lab/dispatch_lab.py`, `dispatch_profile.py`, os quatro braços de laboratório em `backends.py` e `tests/test_thor_lab_dispatch.py`.
- **O que **não** foi tocado**: `telescoping.py`, `onion_protocol.py`, `ntor_experiment.py`, `directory.py`, qualquer relay, qualquer constante de protocolo, qualquer primitiva criptográfica.

## 1. Delta de modelo de ameaças: nenhum metadado novo

| Propriedade | Controlo | Variantes | Evidência |
|---|---|---|---|
| Formato de frame | `frame(packet)` = `!I` + bytes | idêntico | `test_variant_does_not_change_cryptographic_work` + bytes de fio medidos iguais (`wire_up/wire_down` idênticos em `campaign-01`) |
| Sequências por hop | incremento de 1 por comando | idêntico (derivado aritmeticamente) | `test_variant_preserves_payload_integrity_and_sequence_allocation` compara as sequências finais com o controlo |
| Stream IDs por hop | atribuídos no `OPEN` | idêntico (sem alteração) | os testes de isolamento usam três streams e dois circuitos |
| AEAD por camada | `seal`/`open_sealed` | mesma contagem de chamadas | `test_variant_does_not_change_cryptographic_work` (contagem medida no caminho real) |
| Ordem de comandos | FIFO sob `_send_lock` | idêntica | teste de integridade + validação de ACK por `write_pipelined` |
| Tamanho de lote | ≤ `MAX_PIPELINE_DEPTH` = 4 | idêntico | `test_batch_and_payload_limits_fail_closed_for_every_variant` |
| Bytes na rede | payload + AEAD + headers | idêntico | `wire_up_ratio` / `wire_down_ratio` iguais entre braços em `campaign-01` |

Nenhuma variante remove autenticação, criptografia, padding (que não existe no caminho atual) ou controlo de admissão.

## 2. Isolamento entre circuitos, clientes e streams

- Cada variante opera apenas sobre o objeto cliente daquele circuito (`self.hops`, `self._send_lock`, `self._pending_replies`). Não há estado de módulo mutável no caminho de envio.
- O buffer de `io_batch` é local a **uma** chamada de lote de **uma** stream; é libertado no fim da chamada e nunca é reutilizado entre streams ou circuitos. Não há *buffer pool* partilhado.
- O cache de AAD é **por circuito** (`self._lab_aad`), indexado pelo `relay_id` do próprio circuito; é descartado quando o cliente é fechado. Não há cache global.
- Testes: `test_streams_stay_isolated_within_one_circuit` (3 streams com payloads distintos) e `test_two_circuits_stay_isolated` (2 clientes independentes, escritas concorrentes).

## 3. Chaves e material criptográfico

- **Nenhuma chave é armazenada em cache.** O único valor memorizado é `REQUEST_AAD_PREFIX + relay_id`, que é *dados associados públicos*: o mesmo valor já é reconstruído a cada camada e não é segredo nem autentica identidade sozinho.
- Nenhuma variante muda a origem, o ciclo de vida ou a destruição das chaves: `ClientHop.keys` continua a ser o único detentor, e `close()` continua a limpar `hops`.

## 4. Ordenação, ACKs e correlação

- `_register_pending(sequence, stream_id)` mantém a chave de correlação por hop; a decodificação usa a sequência **do hop** (`base_sequences[hop_index] + index`) e o **stream id do hop**, exatamente como o controlo.
- Uma chave duplicada continua a falhar (`_register_pending` levanta `ValueError`).
- Um ACK que não autentica falha fechado: `test_relay_failure_surfaces_as_error_and_closes_circuit` injeta uma falha de `_open_reply` e verifica que o circuito é fechado (`client._writer is None`) em vez de ignorar a resposta.

## 5. Backpressure e limites de memória

| Limite | Controlo | Variantes |
|---|---|---|
| Comandos por lote | ≤4 (`MAX_PIPELINE_DEPTH`) | igual, validado antes de qualquer I/O |
| Bytes por comando | ≤256 KiB (`STREAM_WRITE_MAX_BYTES`) | igual |
| Buffer de lote | n/a (um write por comando) | ≤4 × (4 + 256 KiB + cabeçalhos) ≈ 1 MiB, local e libertado no fim |
| Admissão no relay | 4 comandos / 2 MiB por stream / 16 MiB por circuito | inalterada |
| Orçamento de comandos do circuito | `MAX_COMMANDS_PER_CIRCUIT` | inalterado e testado fail-closed |

`io_batch` reduz o número de chamadas de escrita, **não** o número de comandos nem bytes; portanto não contorna nenhum limite de admissão.

## 6. Cancelamento, falha e shutdown

- Cancellation durante a espera de ACK: idêntica ao controlo (fecha o circuito), porque o `try/except CancelledError` foi replicado.
- Exceção no encode ou na escrita: pendentes canceladas, circuito fechado (`await self._close_unlocked()`), como no controlo.
- `close()` é idempotente e drena `_pending_replies`, `_active_duplex_streams`, `_write_queues` e a task leitora (`test_close_drains_pending_state`).
- Lote vazio, lote acima de 4 comandos e payload acima de 256 KiB falham com `ValueError` **antes** de escrever, e o circuito continua utilizável (`test_batch_and_payload_limits_fail_closed_for_every_variant`).

## 7. Risco residual (declarado, não resolvido)

1. **Temporalidade na rede.** `io_batch` junta 4 frames num único write. Isso altera a forma como os frames chegam ao primeiro salto (uma rajada em vez de quatro escritas). Não é um vazamento novo — os mesmos bytes, os mesmos comandos, as mesmas sequências — mas é uma **mudança de padrão temporal observável** pelo guarda, e a literatura de traffic analysis mostra que forma de rajada é metadado. Nenhuma alegação é feita nos dois sentidos: não se afirma que melhora nem que piora o anonimato, e **por isso a variante não é adotada** nesta fase (ver `10` §5).
2. **Custo de relay inalterado.** As variantes são apenas do lado do cliente; o laço por comando do relay permanece. Um ganho estrutural exige mexer no relay ou no transporte — explicitamente fora desta fase.
3. **Instrumentação do profiler.** `count_primitives()` substitui temporariamente atributos de `asyncio` e de `loop` e `count_aead_ops()` substitui `seal`/`open_sealed` nos módulos que os usam. É um instrumento de laboratório, restaurado em `finally`, e os testes verificam a restauração. Não é usado em nenhum caminho de produção.
4. **Sem auditoria independente.** Este documento é uma revisão interna, não uma auditoria. Nenhuma variante deve ser descrita como "segura" com base nele.

## 8. Evidência de teste (30 casos, `tests/test_thor_lab_dispatch.py`)

| Área | Teste | Resultado |
|---|---|---|
| Configuração | variantes explícitas, controlo por omissão, nome inválido rejeitado, scheduler justo rejeitado | pass |
| Ordenação/sequências | sequências finais idênticas ao controlo, integridade do payload | pass (3 variantes) |
| Criptografia | contagem de `seal`/`open` idêntica ao controlo no caminho real | pass (3 variantes) |
| Isolamento | 3 streams no mesmo circuito; 2 circuitos independentes | pass (3 variantes) |
| Limites | lote vazio/5 comandos/payload >256 KiB rejeitados, circuito continua a funcionar | pass (controlo + 3 variantes) |
| Orçamento de comandos | fail-closed ao esgotar o orçamento | pass (controlo + 3 variantes) |
| ACK inválido | falha injetada fecha o circuito | pass (3 variantes) |
| Shutdown | estado pendente drenado, `close()` idempotente | pass (3 variantes) |
| Concorrência | batches concorrentes em 4 streams, sem starvation | pass |
| Instrumentação | contadores restaurados, custos mensuráveis | pass |

Conclusão da revisão: as variantes **não introduzem** superfície nova de chaves, isolamento, autenticação ou limites; introduzem uma mudança de temporalidade de rede que não foi avaliada e que, por si só, impede adoção sem estudo de traffic analysis. A decisão de engenharia está em `10-DISPATCH-BATCHING-RESULTS.md`.

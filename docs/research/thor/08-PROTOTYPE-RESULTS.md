# 08 — Protótipo isolado do caminho quente: medição e decisão de integração

- **Código do protótipo**: `src/anonlab/thor_lab/fast_path.py` (commit `1aa9130539a30c7ab7c62f116b4fa8771709c584`).
- **Artefato**: `experiments/thor-lab/fastpath-01.json`; log em `experiments/thor-lab/logs/fastpath.log`; 3 000 repetições por operação, medianas e p95, `cryptography 50.0.2`, Windows 10, Python 3.14.6, 4 vCPUs.
- **Regra do protótipo**: cada candidato é **byte-idêntico** ao caminho atual. O próprio benchmark verifica isso antes de medir (`shared_cipher.encrypt(...) == fresh_cipher.encrypt(...)` e round-trip via `open_sealed`), então nenhum candidato pode "ganhar" mudando os bytes.
- **Escopo**: microbenchmark de operações isoladas + uma campanha end-to-end de 144 trials (`06`). Não é protocolo novo; não altera o modelo de ameaça.

## 1. O que foi medido (mediana, ns)

| Operação | 1 KiB | 16 KiB | 256 KiB |
|---|---|---|---|
| Construir objeto AEAD (`ChaCha20Poly1305(key)`) | 3 700 | 3 700 | 3 700 |
| `seal` com objeto novo | 10 200 | 31 800 | 480 900 |
| `seal` com objeto compartilhado | 5 000 | 26 900 | 466 600 |
| `open` com objeto novo | 15 400 | 34 000 | 425 700 |
| `open` com objeto compartilhado | 5 200 | 28 400 | 461 100 |
| Cópia do corpo (`plaintext[header:]`) | 1 100 | 2 900 | 15 200 |
| `memoryview` do corpo (sem cópia) | 1 400 | 1 400 | 1 300 |
| `frame()` concatenando header+payload | 1 700 | 3 200 | 16 300 |
| `struct.pack` do header isolado | 1 100 | 1 100 | 700 |
| Dict de despacho construído por comando | 1 000 | 2 100 | 1 000 |
| Dict de despacho cacheado | 400 | 700 | 800 |
| **1 comando completo de 1 hop** (open + cópia + re-frame + seal) | **13 100** | **83 400** | **1 092 850** |
| Teto teórico de goodput em cadeia serial de 3 hops | 208 Mb/s | 524 Mb/s | 640 Mb/s |

## 2. O que isso diz sobre o gargalo

- **AEAD é o custo dominante por hop em volume** (seal+open = 66% do comando de 16 KiB e 85% do de 256 KiB), mas o teto de goodput que ele impõe (524–640 Mb/s) está **14–34× acima do goodput medido** (18,8–37,8 Mb/s no tier lab).
- **Cópias e framing são pequenos**: ~7% do comando de 16 KiB e ~3% do de 256 KiB.
- **A construção de objeto AEAD só importa em mensagens minúsculas** (28% do comando de 1 KiB, 4,4% em 16 KiB, 0,34% em 256 KiB).
- Portanto, a conclusão da Fase 4 é a mesma que a decomposição end-to-end já indicava (`03`): **o custo está no escalonamento e no despacho por comando (tasks, futures, locks, timers, round-trips), não nas operações criptográficas nem nas cópias.**

## 3. Decisão por candidato (com custo de privacidade quando existe)

| Candidato | Ganho medido por comando/hop | Ganho máximo no caminho | Decisão | Motivo |
|---|---|---|---|---|
| Cache do objeto AEAD por chave | 3,7 µs (28% a 1 KiB; 4,4% a 16 KiB; 0,34% a 256 KiB) | <5% no volume | **rejeitado** | abaixo da resolução das comparações; manteria material de chave vivo em cache de processo (custo de privacidade não nulo) por ganho não demonstrável |
| Cache do AAD | 0,1–0,4 µs | <0,5% | **rejeitado** | ruído de medição |
| `memoryview` no corpo (sem cópia) | 1,5 µs (16 KiB); 13,9 µs (256 KiB) | ~1–2% | **rejeitado agora** | exigiria mudança invasiva em arquivo de 3 000 linhas com benefício não demonstrável end-to-end; registrado como dívida técnica |
| `frame()` sem concatenação | 0,6–15,6 µs | ~1,5% | **rejeitado agora** | mesmo motivo |
| Hoist do dict de despacho | 0,2–1,4 µs | <1% | **rejeitado agora** | ganho real, mas abaixo da resolução; candidato natural para o próximo PR junto de P1 |
| **Tamanho de comando 64–256 KiB** | não é micro-otimização: muda o número de comandos | **+72% goodput, −64% TTFB** | **adotado como recomendação de configuração** | medido end-to-end, sem tocar em bytes de protocolo, sem custo de privacidade |

Nenhum arquivo de protocolo foi modificado nesta fase: `onion_protocol.py` e `telescoping.py` estão byte-idênticos ao commit base. A única mudança de código é o harness e este protótipo de medição. Portanto **não existe regressão de privacidade possível** nesta entrega — e também não existe melhora de desempenho integrada, porque nenhum candidato a demonstrou.

## 4. O que foi validado

| Verificação | Comando | Resultado |
|---|---|---|
| Testes do harness THOR | `python -m pytest tests/test_thor_lab_*.py` | **33 passed, exit 0** em três re-execuções após o endurecimento do timeout do teste AEGIS (ver `EVIDENCE.md` §7.3–7.4; uma execução anterior, sob carga do host, teve um `TimeoutError` transitório, investigado e corrigido sem alterar nenhuma asserção) |
| Suíte completa do repositório | `python -m pytest tests/` | **321 passed, 11 skipped, 1 failed** (falha pré-existente em `test_onion_protocol.py::test_three_hop_persistent_circuit_checks_monotonic_sequence`, teardown do Windows: `relay-3.log` ainda aberto por subprocesso; não toca no código desta entrega) |
| Integridade dos trials | `summary.json` de cada run | `integrity_failures: 0` e `error_records: 0` nos 144 + 54 + 12 + 12 registros |
| Digest do bruto | `python -m anonlab.thor_lab verify <run>` | `ok: true` nos quatro runs |
| Byte-identidade dos candidatos | asserção interna do `fast_path` | aprovada antes de qualquer medição |

## 5. O que realmente moveria a agulha (próximo protótipo, com critérios)

**P1 — transporte fora do `asyncio` por comando.** Duas variantes isoladas, ambas avaliáveis com o harness desta entrega:

1. **Despacho em lote em Python**: manter o protocolo e agrupar comandos por *tick* do loop (ler N frames, processar em um único callback, escrever respostas em lote), removendo uma `Future`/task/lock por comando.
   - Critério de aceitação: goodput AEGIS em 256 KiB ≥ 2× o atual (≥ 44 Mb/s no lab) **e** latência p95 de round-trip de 1 KiB não pior que +10%. Se falhar, o protótipo é descartado.
2. **Transporte Rust/tokio**: mover framing+AEAD+despacho para um worker Rust, mantendo o protocolo de fio.
   - Critério de aceitação: fator cripto+dispatch de 3,0–4,5× reduzido para <1,2×, mantendo o mesmo formato de envelope e o mesmo modelo de ameaça; sem novo metadado observável (nada de CID/spin bit, pois não é QUIC).
   - **Bloqueio atual**: esta máquina não tem `rustc` nem `cargo` (verificado com `Get-Command`, ambos ausentes). Um protótipo Rust não compilado e não medido não é evidência, então ele não foi escrito nem declarado.

**P2 — ACK agregado / window update em lote** para atacar o overhead de 18–35% em mensagens pequenas (`06` §4). Critério: overhead de 1 KiB abaixo de 10% sem perda de integridade nem deadlock em stream esparso (o timer de 2 ms existe exatamente para isso — `telescoping.py:122,1782-1790`).

**P3 — testar `MAX_PIPELINE_DEPTH` > 4 em protótipo isolado**, com os mesmos limites de bytes em voo, para separar "round-trip por comando" de "janela pequena". Critério: ganho de goodput em volume com p95 de latência sob contenção medido.

## 6. Conclusão da fase de protótipo

A meta de 90% exige ~5–9× mais goodput do que o protótipo entrega hoje. As medições desta fase mostram que ~95% desse déficit **não** está em criptografia nem em cópias — está na arquitetura de despacho. Por isso a recomendação não é otimizar o laço atual, e sim prototipar o transporte (P1), com os critérios acima, antes de qualquer nova rodada de micro-otimização. A meta permanece inalterada: **≥90% da Surface, com privacidade igual ou superior à do Tor** — e hoje o AEGIS está em ~10–22% da Surface no tier lab, sem número em caminho real.

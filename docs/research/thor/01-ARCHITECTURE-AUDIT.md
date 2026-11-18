# 01 — Auditoria da arquitetura de transporte e relays

- **Revisão auditada**: `d8b84d531a77318d578224c9ece9fd3bab184037` (branch base `perf/reproducible-baseline-plan`)
- **Versão do pacote**: `aegis-anon-lab 0.26.0` (`pyproject.toml`)
- **Escopo**: código-fonte em `src/anonlab/`, artefatos em `experiments/`, documentos em `docs/`.
- **Natureza deste documento**: auditoria técnica. Nenhuma afirmação aqui é uma prova de anonimato, de segurança ou de desempenho em WAN. As medições desta entrega estão em `06-LAB-RESULTS.md`, `07-PUBLIC-RESULTS.md` e `08-PROTOTYPE-RESULTS.md`, sempre com o SHA completo do artefato bruto.

## 1. Método

1. Leitura integral dos módulos do caminho de dados: `onion_protocol.py`, `onion_relay.py`, `relay.py`, `echo_server.py`, `_crypto.py`, `telescoping.py` (hot path: bootstrap, dispatch de comandos, streams duplex, scheduler, window updates, `close()`), `network_impairment.py` e `benches` correlatos.
2. Reconciliação com os artefatos de benchmark já existentes no repositório (`experiments/*.json`, `*REPORT*.md`) e com os avisos de escopo que eles próprios declaram.
3. Medição própria e reproduzível do caminho real (não de um modelo) com o harness `anonlab.thor_lab`, que usa o protótipo como biblioteca. Todo número citado tem artefato bruto, manifesto e digest.
4. Nada foi reescrito: a auditoria descreve o código como está, inclusive as limitações que os próprios documentos do repositório já reconhecem.

## 2. Inventário de componentes

| Componente | Papel | Criptografia | Estado real |
|---|---|---|---|
| `relay.py` | Encaminhador TCP puro (`_pipe`, chunk de 64 KiB) | nenhuma | testbed de desempenho, explicitamente não é protocolo de anonimato (`relay.py:1-7`) |
| `onion_protocol.py` | Envelopes binários v2 com cabeçalho autenticado (versão, next_port, `payload_len`, `circuit_id`, `sequence`) | ChaCha20-Poly1305 por camada, chaves **pré-compartilhadas por execução** | protótipo de laboratório |
| `onion_relay.py` | Relay de envelopes, um frame por vez, `read_frame`/`wrap_response` | `InvalidTag` tratado como falha fail-closed | protótipo de laboratório |
| `ntor_experiment.py` | Handshake ntor-like (X25519) + KDF MALEBOLGE | X25519 + HMAC-SHA256/HKDF; KDF sem revisão independente | experimento |
| `telescoping.py` | Circuito telescópico real: extensão hop a hop, AEAD por hop, comandos multiplexados, streams duplex, crédito de leitura, scheduler de escrita | handshake ntor-derived + Ed25519 para identidade de link + AEAD por hop | protótipo; **é o caminho de dados atual** |
| `directory.py`, `route_selection.py` | descritores assinados, seleção de rota | Ed25519, SHA-256 | v0.23.0, com limites declarados |
| `privacy_eval.py`, `trace_dataset.py`, `simulator.py` | avaliação de privacidade sintética | — | baseline de centroide mais próximo; sem traces reais |
| `pir_*`, `secret_sharing.py` | PIR de dois servidores, XOR shares, RPC com HMAC | X25519, HMAC-SHA256, TLS opcional em demo | ramo separado; não integrado ao circuito |
| `network_impairment.py` | shaper de enlace em espaço de usuário (delay, jitter, taxa) | — | **não** modela perda, retransmissão ou fila de pacotes (`network_impairment.py:1-7`) |
| `echo_server.py` | destino de eco loopback | — | suporte de medição |

### 2.1 Dois caminhos de dados, maturidades diferentes

- **Caminho A — envelopes v2** (`build_request`/`parse_request_layer`): chaves **pré-compartilhadas** por execução (`onion_protocol.py:83-95`), sem AKE, sem forward secrecy; `sequence` monotônica e `circuit_id` amarrados ao AEAD (`onion_protocol.py:104-126`). Cada `DATA` no relay terminal abre **uma nova conexão TCP ao destino** e usa o eco para responder (`onion_relay.py:90-97`), o que serializa estritamente requisição/resposta.
- **Caminho B — telescoping**: handshake `CREATE`/`CREATED` com `relay_respond` e chaves por hop (`telescoping.py:1095-1102`), links autenticados por Ed25519 (`telescoping.py:296-380`), comandos multiplexados por stream (`_COMMAND_HEADER = !QIB`, `telescoping.py:81`), crédito de leitura de 64 KiB inicial e 256 KiB máximo (`telescoping.py:116-117`), pipeline de escrita limitado a 4 comandos em voo (`telescoping.py:110`), scheduler de escrita opcional (`fair_write_scheduling`, `telescoping.py:1875`).

O THOR Lab mede o **caminho B**, porque é o caminho de dados que se pretende evoluir. O caminho A permanece como referência histórica e não é comparável.

## 3. Custo por comando no caminho B (modelo derivado do código)

Para cada comando enviado pelo cliente, por hop:

| Etapa | Onde | Observação de custo |
|---|---|---|
| `open_sealed` | `telescoping.py:1112-1115` | instancia `ChaCha20Poly1305(key)` **a cada mensagem** (`onion_protocol.py:83-95`), sem cache de objeto de cifra |
| AAD | `telescoping.py:140-141` | `prefixo + relay_id.encode("ascii")` recriado por chamada; `relay_id` é hex de 40 caracteres derivado do digest de identidade |
| Decodificação do cabeçalho | `telescoping.py:1118` | `struct.unpack_from`, barato |
| Cópia do corpo | `telescoping.py:1124` | `plaintext[_COMMAND_HEADER.size:]` copia o payload inteiro por hop |
| Nome da operação | `telescoping.py:1126-1131` | **dicionário literal construído a cada comando** |
| Leitura do frame | `telescoping.py:1107` | `asyncio.wait_for(read_frame(reader), timeout=30)` cria um timer por comando |
| Resposta | `telescoping.py:989-1011`, `_seal_reply` | novo `seal` + `frame` (header + payload concatenados) por hop |
| Encaminhamento | `telescoping.py:923-943` | `Future` + lock + task por escrita encaminhada |

Consequência estrutural: nesses pontos o custo por byte cai e o custo por **comando** domina. Isso é exatamente o que os artefatos do repositório já mostram — `handle` do relay com 26,1% do tempo acumulado e `seal` com 7,1% (`experiments/cprofile-after-cache-v0.18.0.txt:14,27`) — e é reproduzido nas medições desta entrega (§5 de `06-LAB-RESULTS.md`).

## 4. Achados (F1–F12)

Cada achado tem evidência no código, impacto e implicação para a meta de 90% da Surface ou para o modelo de anonimato.

**F1 — Serialização por requisição no caminho de eco.** `onion_relay.py:57-104` lê um frame, escreve no upstream, espera `readexactly(len(payload))` e só então responde. O caminho B melhora isso com `write_pipelined`, mas com profundidade ≤4 (`telescoping.py:110,1714-1754`). Impacto: throughput limitado por RTT, não por banda. Implicação: nenhuma melhoria de CPU compensa isso — é preciso pipeline maior ou controle de fluxo por janela.

**F2 — Alocação por comando.** F1 + §3: dicionário de operações por comando, AAD por chamada, cópia de corpo por hop, `frame()` concatenando header e payload. Impacto: CPU e GC por byte caem com o aumento do comando; comandos de 16 KiB pagam esse custo 16× mais que comandos de 256 KiB. Já medido no repositório: 16 KiB→256 KiB ganha 37,8% (`experiments/WRITE_BATCHING_REPORT_V0.16.0.md:15-19`).

**F3 — AEAD instanciado por mensagem.** `onion_protocol.py:83-95`. Impacto: alocação de objeto C por mensagem e `os.urandom(12)` por mensagem; o nonce aleatório é correto para segurança, mas o objeto de cifra poderia ser reutilizado por chave. Não altera bytes em claro/cifrado.

**F4 — Estado de relay sem limite superior efetivo.** `RelayObservation` é anexado a cada comando (`telescoping.py:1034,1047`); `CircuitReplayGuard` nunca remove entradas (`onion_protocol.py:41-67`) e é global de módulo (`onion_relay.py:29`), falhando fechado ao encher. Impacto: memória cresce com o número de circuitos do processo; o teste de 100 mil circuitos é o teto. Implicação de privacidade: o guard local não é defesa distribuída (o próprio docstring diz isso).

**F5 — Controle de fluxo por crédito com limiar fixo.** `telescoping.py:116-122` (64 KiB de lote, 2 ms de timer). O repositório já documentou pausas de até 748 ms e perda de 45,06% de goodput ao reduzir o limiar para 16 KiB (`RELAY-STAGE-DIAGNOSTICS-REPORT-v0.22.0.md:41,66-72`, `docs/WINDOW_UPDATE_BATCH_SENSITIVITY_V0.22.0.md:21,28`). Implicação: o controle de fluxo é um gargalo de throughput de primeira ordem, não um detalhe.

**F6 — Sem controle de congestionamento nem pacing próprios.** O escalonamento é do TCP do kernel; não há AQM, não há pacing, não há como trocar forma de rajada por latência — exatamente o botão que uma rede de anonimato precisa para casar *shaping* com desempenho. `relay.py:15` fixa 64 KiB; `telescoping.py` não tem CC.

**F7 — Transporte é loopback por construção.** `_ensure_loopback` rejeita qualquer host que não seja IPv4 loopback (`telescoping.py:144-150`); `RelayDescriptor` valida o mesmo (`telescoping.py:230-233`); `serve_node` só aceita loopback (`telescoping.py:2935-2937`); o CLI do relay também (`onion_relay.py:148-149`). **Consequência direta para a missão**: não existe hoje como medir AEGIS em caminho real. O tier público mede Surface × Tor; AEGIS não tem número público. Isso não é uma limitação de medição — é uma limitação de arquitetura que precisa ser resolvida antes de qualquer alegação de 90% em WAN.

**F8 — Uma conexão TCP por circuito, todas as streams dentro dela.** `telescoping.py:1858-1865`. Head-of-line blocking na camada TCP entre streams independentes; uma stream interativa fica atrás de uma transferência em massa no mesmo socket. O scheduler justo (`fair_write_scheduling`) endereça ordem de comandos, não HOL de transporte.

**F9 — Orçamento de vida do circuito.** `MAX_COMMANDS_PER_CIRCUIT = 4096` (`telescoping.py:88`) e `MAX_COMMANDS_PER_CIRCUIT` consumido por comando (`telescoping.py:1121-1122`). Com 16 KiB por comando isso é ~64 MiB por circuito antes de reconstruir; a reconstrução custa handshake por hop e é medida separadamente (`setup_ms`).

**F10 — Criptografia e protocolo proprietários.** Não é compatível com o wire do Tor; suíte fixa ChaCha20-Poly1305; KDF MALEBOLGE sem revisão independente (`docs/THREAT_MODEL.md:23`); caminho A usa PSK por execução. Nenhuma rotação de chave no caminho B.

**F11 — Ciclo de vida do cliente.** `TelescopingClient.close()` cancela e aguarda a task leitora (`telescoping.py:2924-2926`). O harness observou "Task was destroyed but it is pending" quando um cliente é descartado sem `close()` — comportamento do harness, corrigido com `after_trial()`; registrado aqui porque uma futura integração precisa fechar circuitos explicitamente.

**F12 — Instrumentação.** `collect_relay_metrics` (deque limitado a 8192) e `collect_write_metrics` (4096) existem e são opt-in, e registram apenas nomes de estágio/operação e tempos, nunca payloads ou endereços (`telescoping.py:458-519`). Bons para diagnóstico; quando ligados, custam CPU no caminho quente.

## 5. Limitações do protocolo atual, explícitas

1. Sem AKE no caminho A; no caminho B o handshake existe, mas o KDF é experimental e não revisado.
2. Sem defesa contra observador global; sem cover traffic constante; sem padding de tráfego no caminho de dados (o único padding existente é o modelo de tamanho no avaliador sintético).
3. Sem resistência a website fingerprinting medida com atacante forte (ver `04-THREAT-MODEL.md` §4).
4. Descritores são entradas em memória no harness; a autorização por diretório existe em `directory.py`, mas não está no caminho de dados do `telescoping` sem configuração explícita.
5. Sem multicast, sem mistura, sem isolamento de exit por cliente; `allowed_destinations` é allowlist por relay.
6. `MAX_FRAME_BYTES = 16 MiB` (`onion_protocol.py:31`) é um limite de alocação; frames grandes são copiados em múltiplas camadas.

## 6. Dependências Python: o que pode ser substituído ou acelerado

| Dependência | Uso | Custo real | Caminho de aceleração |
|---|---|---|---|
| `cryptography` (extra `onion-lab`, `>=42`) | AEAD, X25519, Ed25519 | 50.0.2 instalada; operações de AEAD custam µs por mensagem; a instanciação de objeto por mensagem é desperdício evitável | cache de objeto por chave, `AESGCM` em hardware com AES-NI (medir!), ou binding Rust |
| `asyncio` | concorrência do testbed | timer por espera (`wait_for`), task por escrita encaminhada, `Future` por comando | mover dispatch para Rust/`tokio`; ou reduzir timers/futures no Python |
| `struct` | framing | barato, mas concatenar header+payload copia | `struct.pack_into` em buffer pré-alocado; escrita em duas chamadas |
| `random` (stdlib) | geração de payload de teste | irrelevante | — |
| — | não há numpy/scipy/psutil; não há Rust | — | protótipo Rust não é possível nesta máquina (sem `rustc`/`cargo`); hipótese registrada em `03-BOTTLENECKS.md` §5 |

## 7. O que o repositório mede hoje e o que não mede

Medido: RTT e goodput de eco em loopback, em várias configurações de batching/window/scheduler, com perfis de shaper; cProfile do caminho duplex.

Não medido (até esta entrega): CPU e RSS por trial; p99; TTFB padronizado; bytes de fio por trial; overhead de banda; tempo de estabelecimento comparado entre braços; múltiplos streams concorrentes com métricas completas; Tor; rede real; qualquer coisa além de um host.

A lacuna de "wire bytes" era a mais grave para a meta de 90%: sem contar bytes no enlace de acesso não existe denominador para o overhead de anonimato. O harness desta entrega fecha essa lacuna com um proxy contador por braço (`src/anonlab/thor_lab/counting_proxy.py`).

## 8. Julgamento da auditoria

O protótipo é um **testbed de pesquisa correto e honesto**, com documentação de limites acima da média, e um **caminho de dados estruturalmente incapaz** de se aproximar de 90% da Surface: ele serializa por comando, paga alocação e cópia por camada, não tem congestion control próprio e não pode sair do loopback. As prioridades derivadas estão em `03-BOTTLENECKS.md`; o que foi efetivamente otimizado e validado nesta entrega está em `08-PROTOTYPE-RESULTS.md`.

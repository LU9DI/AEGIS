# 02 — Matriz comparativa de tecnologias

- **Pergunta**: quais tecnologias podem elevar o AEGIS em direção às duas metas inegociáveis (privacidade ≥ Tor em modelos comparáveis; desempenho ≥ 90% da Surface) sem regressão de privacidade?
- **Regra de decisão**: nenhuma adoção por novidade. Cada linha tem benefício esperado, custo de integração, maturidade, licença/dependências, riscos de segurança, impacto em latência/throughput/memória/banda, compatibilidade com o modelo de anonimato e veredito.
- **Status de verificação**: "primária" = especificação/repositório oficial consultado; "secundária" = reportado por terceiros e não confirmado no primário nesta auditoria. Números de desempenho de terceiros não são medições nossas; as nossas estão em `06`–`08`.

## 1. Enquadramento

Duas frases que governam a matriz:

1. **Escolher transporte não concede anonimato.** QUIC/HTTP3/MASQUE/OHTTP mudam *qual metadado existe e quem o vê*; unlinkability vem de diversidade de caminho, cellização/framing fixo, padding e seleção de guarda. Trocar TCP por QUIC não move a privacidade em direção ao Tor por si só.
2. **"90% da Surface" só é mensurável em goodput e latências de resposta.** Um salto extra custa, no mínimo, um RTT de caminho; nenhum transporte remove isso. A meta é uma meta de *overhead de implementação*, não de física.

## 2. Matriz

| Tecnologia | Benefício esperado | Custo de integração (Python / Rust) | Maturidade (na data da auditoria) | Licença / dependências | Riscos de segurança | Impacto em latência / throughput / memória / banda | Compatibilidade com o anonimato do AEGIS | Veredito |
|---|---|---|---|---|---|---|---|---|
| **Rust + Tokio + Quinn** | transporte QUIC em Rust puro, streams, datagramas, `quinn-proto` testável sem sockets | Python: indireto (sidecar ou PyO3). Rust: baixo–médio (runtime tokio, rustls/ring) | quinn 0.11.x, mantido desde 2018; único RUSTSEC (2021, corrigido) (primária: crates.io/RUSTSEC) | MIT OR Apache-2.0; rustls + ring; MSRV recente | 0-RTT replayable; CID como unidade de linkability; sem auditoria independente encontrada (secundária) | handshake 1 RTT; CPU de cripto pequeno frente ao ganho de syscalls; memória por conexão de dezenas de KB a MB | esconde payload; expõe IP/porta/tempo/tamanho; exige spin bit desligado e rotação de CID | **prototipar** — melhor substrato Rust, condicionado a resolver metadados |
| **s2n-quic (AWS)** | CUBIC + pacing + GSO + PMTUD prontos; CIDs desacoplados do endereço; FIPS | Rust: médio–alto (toolchain C, CMake; GSO em Linux ≥5) | releases mensais, mantido pela AWS (primária: repositório) | Apache-2.0; puxa s2n-tls e aws-lc (C/asm) | superfície nativa maior; boletim de segurança de 2026 reportado por CERT nacional (secundária, não confirmado) | throughput líder via GSO; build complexo; mesmo perfil de latência do QUIC | igual ao QUIC; CID desacoplado ajuda migração e também rastreio se reutilizado | **adiar** — só se FIPS ou throughput máximo for requisito |
| **QUIC v1 (RFC 9000/9001/9002)** | handshake 1-RTT, streams sem HOL entre si, loss recovery, criptografia obrigatória | do zero: meses; via quinn/s2n: baixo | RFCs de 2021, implantação ubíqua | IETF, sem licença de código | 0-RTT replayable por desenho; spin bit = oráculo passivo de RTT (RFC 9000 §17.4); CID como elo; limites de amplificação | vs TCP+TLS: um RTT a menos, sem HOL entre streams; CPU/pps maior que TCP de kernel | esconde conteúdo apenas; cadência de ACK, tamanhos, spin bit e reuso de CID vazam | **prototipar** — transporte candidato com spin bit off, rotação de CID, 0-RTT proibido para requisições sensíveis |
| **HTTP/3 + datagramas (RFC 9114, RFC 9221) + WebTransport** | streams sobre QUIC; datagramas não confiáveis; alcance via navegador | Rust: `h3`+quinn, médio. Python: `aioquic` (não verificado nesta auditoria) | RFC 9114 e 9221 (2022); WebTransport ainda Internet-Draft | varia; QPACK adiciona estado | canais laterais de prioridade/QPACK; datagramas sem controle de fluxo → pressão de memória/DoS | overhead de framing por stream; datagramas ajudam fluxos interativos | prioridades e tamanhos por stream observáveis | **adiar HTTP/3; prototipar datagramas** — única capacidade genuinamente ausente no AEGIS |
| **MASQUE CONNECT-UDP (RFC 9298) / CONNECT-IP (RFC 9484)** | tunelar UDP/IP sobre HTTPS; esconde IP do cliente do destino; atravessa firewall | Rust: médio (h3 + capsules). Python: baixo se houver aioquic | RFCs 2022/2023; poucas implementações em produção | varia | o proxy vê IP do cliente **e** destino → ponto único de confiança; abuso/rate limit | +1 RTT e um salto; overhead de encapsulamento; banda extra no proxy | é proxy de um salto: não é mecanismo de anonimato | **adiar** — útil como túnel de entrada, nunca como arquitetura |
| **Oblivious HTTP (RFC 9458)** | relay esconde IP do gateway; gateway esconde conteúdo do relay; reuso de conexão amortiza custo | Rust: baixo (`hpke` + RFC 9292). Python: baixo se houver HPKE (não confirmado) | RFC 9458 (2024); poucas implantações públicas | IETF | quebra sob conluio relay↔gateway; replay é responsabilidade do gateway; tamanho/tempo da requisição vazam; autenticidade da config de chave | +1 RTT por lote; CPU desprezível; padding opcional | forte unlinkability *de requisição* contra par não coludido; não é transporte de volume | **prototipar** — certo para consultas de diretório/consenso, errado para tráfego de dados |
| **HPKE (RFC 9180)** | envelope KEM/KDF/AEAD padronizado, modos base/PSK/auth, selagem única | Rust: baixo (`hpke`). Python: baixo apenas com binding | RFC 9180 (2021), bem implementado | IETF; dependências pequenas | ciclo de vida de nonce/chave é do aplicativo; sem KEM pós-quântico no RFC; reúso de contexto é o erro clássico | µs por operação | bloco de construção; não esconde nada sozinho | **adotar** — primitiva de envelope sob camadas onion/OHTTP, substituindo KDF proprietário quando houver revisão |
| **BLAKE3** | hash/XOF/MAC/KDF rápido, paralelo por árvore, modos `keyed_hash`/`derive_key` | Rust: trivial; Python: wheels prontos | especificação C2SP, não IETF | CC0-1.0 OR Apache-2.0 | **não é AEAD**; `keyed_hash` exige gestão de chave; não é hash de senha | ganho irrelevante no tamanho de pacote do AEGIS; útil para hashing de snapshots/manifests | neutro | **prototipar** — KDF/MAC/hash de integridade, jamais como cifra |
| **CUBIC (RFC 9438)** | padrão loss-based, justo, bem entendido | grátis dentro de quinn/s2n; não exposto ao Python | RFC 9438 (2023), default do Linux | — | slow-start overshoot; assinatura de perda/fila | bom throughput; bufferbloat em buffers rasos | padrão de perda "comum", mas padding que gera fila estrangula o CC | **adotar** como default até medição contrária |
| **BBR (v1/v2/v3, Internet-Draft)** | model-based (BtlBw/RTprop), forte em caminhos com perda | s2n: provider instável; quinn: CC custom | draft-ietf-ccwg-bbr em discussão; adotado por Google/Linux | — | justiça contra fluxos loss-based; inflação de fila; rajadas PROBE_BW | throughput maior, fila/latência maior | rajada de probe é fingerprint e briga com shaping | **adiar** — só depois de medir a assinatura sob padding |
| **Copa / PCC** | CC por atraso/utilitário, fila em pé baixa | implementar (Rust) ou modelar em ns-3 | pesquisa (Copa NSDI'18; Copa+ INFOCOM'22), sem status IETF | código de pesquisa | reage à **nossa própria** fila de padding; sinal de atraso é jogável | latência menor, throughput menor com perda | padding/cover corrompe o sinal de atraso → instabilidade | **rejeitar** — incompatível com caminho shaped |
| **HyStart++ (RFC 9406) + pacing (RFC 9002 §7.7)** | menos perdas em slow start, envio suavizado | baixo; já presente em quinn/s2n | RFC 9406 (2023) | — | taxa de pacing é observável; heurística de atraso erra em caminho shaped | menos perda/latência, pequeno custo de timer | suaviza rajada; taxa constante é, ela própria, um fingerprint | **prototipar** — ganho de latência de baixo risco |
| **Padding de circuito do Tor / WTF-PAD / Adaptive Padding** | framework de padding event-driven implantável; esconde sequência de cells de setup | Rust: médio (máquinas de estado + negociação). Python: fácil de simular | implantado no Tor; especificação estável | Tor: BSD-3-Clause | a própria especificação diz que **o tempo de inter-chegada não é ofuscado**; padding tem fingerprint próprio; custo de banda | ~11 cells no intro, 4 no rendezvous; overhead fixo, latência melhor se bem orçado | esconde setup de onion service nas primeiras 10 cells — não é defesa geral de WF | **adotar como referência de projeto**, não como código |
| **Cover traffic de taxa constante + token buckets** | defesa de tempo/volume mais forte; bucket limita rajada | baixo para implementar; alto custo de banda | bem estudado, sem padrão | — | custo/DoS; cover tem de ser indistinguível do real; mudanças de taxa vazam | banda ≈ taxa × tempo; latência quando a taxa < demanda | esconde tempo e volume; não esconde conteúdo nem extremos | **adiar** — até existir orçamento de banda e modelo de WF escrito |
| **Shadow** | determinístico, roda aplicativos reais (Python/Rust), milhares de nós em um host | médio; Linux-only, dependências de build; Python funciona | ativo, releases recentes | BSD-3 (verificar no repositório) | — (ferramenta de pesquisa) | simula latência/banda; custo de cripto real; não modela offload de kernel | pode testar padding/WF em escala de rede | **adotar** — única ferramenta que roda nosso relay real |
| **ns-3** | PHY/MAC/fila precisos; pesquisa de CC | alto; módulos C++; QUIC é externo | releases recentes; **sem modelo QUIC nativo**; módulo externo desatualizado | GPL-2.0 | — | apenas simulação | topologia/CC, não comportamento de aplicação | **prototipar** — só para perguntas de CC/fila |
| **Mahimahi / tc-netem** | emulação de enlace para aplicativos reais; traços reproduzíveis | baixo; requer root | Mahimahi GPL-3.0; netem no kernel | GPL-3.0 | — | delay/perda em nível de pacote | bom para sanidade de timing | **adotar** para sanidade de enlace |
| **Caminho de dados do Linux (UDP GSO `UDP_SEGMENT`, `sendmmsg`, `MSG_ZEROCOPY`, io_uring)** | um syscall por rajada; segmentação no kernel/NIC | Rust: médio. **Python: inacessível** | `UDP_SEGMENT` desde 4.18, `MSG_ZEROCOPY` 4.14, io_uring 5.1 | kernel GPLv2; ABI de syscall não | io_uring é superfície de ataque grande com histórico de CVEs | ↑ throughput, ↓ custo de syscall em p99 | neutro, mas batching briga com shaping | **prototipar apenas em Rust** — inalcançável a partir de asyncio |
| **Escolha de AEAD: AES-GCM vs ChaCha20-Poly1305** | AES-GCM acelera com AES-NI/VAES/GFNI; ChaCha20 é constante em software | grátis via rustls/aws-lc/cryptography | suites de TLS 1.3 padronizadas (RFC 8439, RFC 8446) | varia | reúso de nonce é catastrófico; AES em software sofre timing de cache | AES-GCM ≥ ChaCha20 em x86 com AES-NI (a confirmar na nossa máquina) | neutro | **adotar** — AES-GCM quando houver AES-NI, ChaCha20 como fallback |

## 3. O que o AEGIS não tem hoje e que estas peças mudariam

Ordenado por impacto na missão, não por novidade:

1. **Não há AKE revisado no caminho de produção** (o caminho A usa PSK; o B usa KDF proprietário). HPKE é a forma de menor custo de trocar isso por construção revisada.
2. **Não há multiplexação de transporte** — todas as streams viajam em um TCP, com HOL blocking entre elas (F8 em `01`). QUIC resolve; dita o custo de metadados (CID, spin bit).
3. **Não há padding no caminho de dados.** O único padding do repositório é o modelo de bucket no avaliador sintético. Tor é referência de *framework*, mas declaradamente não esconde tempo de inter-chegada — copiá-lo não sustenta paridade com o Tor.
4. **Não há pacing nem CC próprios** (F6). Sem esse controle, não há como negociar forma de rajada versus latência, que é o botão central de uma rede de anonimato.
5. **Não há contabilidade de metadados por byte** — o denominador do "90%" não existia. Esta entrega cria (§`src/anonlab/thor_lab/counting_proxy.py`).
6. **Não há harness de nível de pacote.** Loopback + shaper de chunks não separa custo de cripto, de framing e de caminho. Shadow é o próximo passo natural; ns-3 só responde perguntas de fila/CC.
7. **Não há decisão de licença/fornecedores.** Qualquer crate Rust força essa decisão e uma história de supply chain (e FIPS, se necessário).
8. **Não há semântica de migração/fragmentação de caminho.** TCP prende a conexão a um caminho; migração de QUIC é vantagem de mobilidade e risco de linkability ao mesmo tempo.

## 4. Fatos que decidem (e o que ainda precisa ser medido por nós)

Fatos com fonte primária:

1. O spin bit do QUIC é um oráculo passivo de RTT definido em RFC 9000 §17.4 — precisa ser desligado.
2. CIDs são a unidade de linkability; quem escolhe é o endpoint (RFC 9000 §5.1).
3. O padding de circuito do Tor é estreito e não esconde inter-chegada (padding-spec/circuit-level-padding).
4. 0-RTT herdado de TLS 1.3 é replayable (RFC 9001).
5. A privacidade do OHTTP é exatamente não-conluio entre dois partidos (RFC 9458).
6. HPKE padroniza IDs de KEM/KDF/AEAD, não política de rotação de chave/nonce (RFC 9180).
7. BBR não é RFC; CUBIC é o único default loss-based padronizado (RFC 9438).
8. Shadow roda aplicativos reais de forma determinística; ns-3 não tem modelo QUIC nativo.

Perguntas que **só medição própria responde** (e que esta entrega começa a responder):

- Quanto dos 10% de orçamento de desempenho é (a) salto extra, (b) cripto, (c) framing/cópias, (d) padding/cover? Antes desta entrega não havia como decompor; `06-LAB-RESULTS.md` faz a primeira decomposição.
- Algum orçamento de padding que possamos pagar derrota um atacante moderno de WF, ou só o centroide?
- Sob o nosso próprio padding, CUBIC e BBR produzem assinaturas de fila/rajada diferentes em caminho real?
- Qual é o custo por Mbps de AES-GCM vs ChaCha20-Poly1305 nesta máquina, com e sem aceleração?
- Quanto de linkability 0-RTT/resumption adiciona ao nosso modelo de circuito?
- Quanto de banda custa cover traffic de taxa constante no nosso SLO de latência?

## 5. Vereditos consolidados

- **Adotar agora (sem integração de transporte)**: HPKE como primitiva de envelope; CUBIC como default; AES-GCM com fallback ChaCha20; Shadow para simulação; referência de padding do Tor.
- **Prototipar isolado**: QUIC via quinn; HyStart++/pacing; BLAKE3 para integridade de snapshots; datagramas QUIC para fluxos interativos; caminho de pacotes só em Rust.
- **Adiar**: s2n-quic (FIPS/throughput máximo), HTTP/3 completo, MASQUE (apenas túnel de entrada), BBR, cover traffic constante, ns-3.
- **Rejeitar como CC**: Copa/PCC sob caminho shaped.

# AEGIS — Guia didático de arquitetura de privacidade e baixa latência

> **Status:** documento de planejamento e pesquisa. As opções descritas aqui não significam que os protocolos estejam integrados ou habilitados no AEGIS. Consulte o estado do código, as Issues vinculadas e os resultados de CI antes de inferir capacidade operacional.
>
> **Aviso de segurança:** AEGIS é um protótipo de pesquisa recuperado, não uma rede de anonimato pronta para produção ou auditada independentemente. Não o utilize para comunicações sensíveis.

## 1. Objetivo e como ler este guia

Este documento organiza em uma única visão as propostas para melhorar a privacidade, a disponibilidade e o desempenho do AEGIS. Ele separa:

1. **Objetivos de segurança** — o que queremos proteger e contra quem.
2. **Mecanismos complementares** — controles que podem coexistir, como E2EE, minimização de dados e proteção de conexões entre nós.
3. **Alternativas de arquitetura** — opções que devem ser comparadas, como PIR de servidor único, PIR multi-servidor/MPC e TEEs.
4. **Hipóteses de desempenho** — ganhos a medir, nunca presumir.
5. **Estado de implementação** — ideias documentadas não são funcionalidades existentes.

A regra central é: **primeiro medir e definir o modelo de ameaça; depois prototipar; por fim, considerar ativação após testes e revisão independente.** Não remover controles de segurança para melhorar um benchmark isolado.

## 2. Vocabulário essencial

- **Confidencialidade do conteúdo:** intermediários não conseguem ler o payload. TLS protege o canal; E2EE protege o conteúdo entre os endpoints que detêm as chaves.
- **Privacidade da consulta:** o servidor não descobre qual registro o cliente está buscando. E2EE, VPNs e hashes de conteúdo não garantem isso automaticamente.
- **Anonimato de rede:** dificulta vincular uma requisição a um endereço/identidade. OHTTP oferece separação de conhecimento entre relay e gateway sob hipóteses específicas; não é equivalente a Tor em todos os modelos de ameaça.
- **Integridade:** permite detectar alterações. Hashes e provas de Merkle ajudam a verificar dados comprometidos, mas não provam, por si sós, que uma resposta PIR foi calculada corretamente.
- **Verificabilidade da resposta:** o cliente consegue detectar uma resposta incorreta sem revelar a consulta. É um bloqueio separado da confidencialidade do canal e continua exigindo solução explícita.
- **Pseudonimização:** substitui identificadores diretos, mas dados pseudônimos ainda podem ser correlacionados.
- **Latência p50/p95/p99:** mediana e percentis 95/99. Reportar apenas a média pode esconder caudas lentas.
- **Modelo de conluio:** especifica quais servidores ou operadores podem cooperar para combinar informações. “Servidores independentes” é uma hipótese operacional a demonstrar, não uma garantia matemática.

## 3. Mapa de objetivos para mecanismos

| Objetivo | Mecanismos candidatos | O que não garantem sozinhos |
|---|---|---|
| Ocultar o conteúdo de intermediários | TLS; E2EE com chaves nos endpoints | Ocultar IP, tamanho, horário ou padrão de acesso |
| Ocultar qual registro é consultado | PIR; protocolos MPC/PIR multi-servidor | Resposta correta sem mecanismo verificável |
| Separar IP do conteúdo da requisição | OHTTP com relay e gateway separados | Resistência a conluio/correlação global; anonimato equivalente a Tor |
| Proteger conexões entre servidores | WireGuard/Tailscale ou TLS mútuo, conforme o caso | Anonimato do usuário ou privacidade do índice consultado |
| Verificar integridade de objetos | Hashes, manifests autenticados, árvores de Merkle | Disponibilidade, confidencialidade ou correção de cálculo PIR |
| Reduzir exposição em caso de vazamento | Minimização de dados, retenção curta, pseudônimos rotativos | Anonimização automática |
| Reduzir custo de acesso repetido | Cache/prefetch com políticas de privacidade | Ausência de vazamento por padrões de cache |
| Reduzir latência | Medição, QUIC/HTTP/3, cache, execução próxima do usuário | Ganho universal sem benchmark real |

## 4. Linha de base obrigatória

Antes de escolher uma tecnologia, registrar:

- forma e tamanho do banco de dados, quantidade de registros e tamanho típico de cada registro;
- distribuição geográfica e topologia de cliente, relay, gateway e servidores de dados;
- versões de runtime, dependências, sistema operacional, hardware e configuração de rede;
- latência p50/p95/p99, vazão, erros, CPU, memória e bytes transferidos;
- resultados com cache frio/quente, concorrência realista, perda e reordenação de pacotes;
- comportamento com nós indisponíveis, timeouts, cancelamento, repetição e respostas malformadas;
- quais dados cada componente pode observar, registrar, correlacionar ou reter.

Todos os experimentos precisam incluir comandos de reprodução, configuração, sementes/dados sintéticos quando aplicável e limitações. Não comparar números produzidos em condições diferentes como se fossem equivalentes.

## 5. Acesso privado a registros: PIR, MPC e verificabilidade

### 5.1 PIR de servidor único baseado em reticulados

Candidatos de pesquisa incluem SimplePIR/DoublePIR, Spiral e SealPIR. Cada implementação precisa ter escopo, licença, manutenção, parâmetros criptográficos, dependências e compatibilidade verificados antes de adoção.

Avaliar separadamente:
- custo de pré-processamento/hints e armazenamento;
- custo online de consulta, resposta e bytes de rede;
- CPU e memória de cliente e servidor;
- tamanho do banco, largura dos registros, concorrência e comportamento em hardware alvo;
- privacidade de consulta e vazamentos laterais por tempo, cache, metadados ou estado reutilizado.

Uma implementação de pesquisa ou benchmark favorável não equivale a um componente seguro para produção.

### 5.2 MPC e PIR multi-servidor

Uma arquitetura multi-servidor pode distribuir o trabalho e reduzir a confiança depositada em um único operador, dependendo do protocolo. É necessário especificar o limiar de conluio e a independência administrativa/infraestrutural dos servidores.

O compartilhamento de segredo de Shamir, por si só, não define um protocolo PIR eficiente. O custo depende do protocolo, do layout dos dados, da comunicação, do número de servidores e da recombinação no cliente. Medir falhas parciais, retries e o custo total da rede.

### 5.3 Respostas verificáveis

Privacidade e correção são propriedades diferentes. Um servidor pode enviar uma resposta falsa por uma conexão TLS válida. Uma prova de Merkle que revela o índice da folha pode comprometer a privacidade e não prova automaticamente que o cálculo PIR foi executado corretamente.

O bloqueio é acompanhado na [Issue #9](https://github.com/LU9DI/AEGIS/issues/9). Não declarar o PIR seguro para dados sensíveis até existir uma solução adequada, testes adversariais e revisão independente.

## 6. Cache, prefetch e índices compactos

Filtros Cuckoo podem ajudar a responder localmente se um item provavelmente pertence a um conjunto, mas não são provas de autenticidade. Estruturas autenticadas podem comprovar inclusão em um compromisso, mas o caminho acessado pode revelar qual item foi consultado.

Antes de habilitar prefetch, definir:
- orçamento de bytes e recursos, expiração, invalidação e versão;
- política de cache, dados obsoletos e proteção contra rollback;
- tratamento de falsos positivos, falhas e retries;
- vazamento de padrões de acesso por cache hit/miss, prefetch e sincronização;
- opt-in experimental e proibição de pré-carregar dados sensíveis sem justificativa explícita.

Acompanhar a [Issue #14](https://github.com/LU9DI/AEGIS/issues/14).

## 7. Separação de confiança: OHTTP, E2EE e tokens cegos

### 7.1 Oblivious HTTP (OHTTP)

No modelo usual, o **relay** observa o endereço de rede do cliente e metadados de tráfego, mas não lê a requisição encapsulada. O **gateway** decifra a requisição e pode ler seu conteúdo, mas recebe a conexão do relay. Essa separação depende da configuração e da hipótese de que os operadores não combinem seus registros.

OHTTP não é automaticamente E2EE entre cliente e destinatário: o gateway é o destinatário criptográfico da encapsulação OHTTP. Também não elimina correlação por horário/tamanho nem equivale a Tor contra todos os adversários. Seguir a RFC 9458 e bibliotecas mantidas.

### 7.2 E2EE na aplicação

Criptografar no cliente com uma biblioteca mantida e uma cifra autenticada (por exemplo, ChaCha20-Poly1305 quando apropriado) protege o payload apenas se as chaves estiverem nos endpoints pretendidos. Documentar troca e rotação de chaves, unicidade de nonce, autenticação do destinatário, replay, recuperação e metadados expostos. Não inventar protocolo criptográfico próprio.

### 7.3 Tokens cegos / Privacy Pass

Tokens cegos podem ajudar em autorização ou controle de abuso sem vincular diretamente a emissão ao resgate, conforme o protocolo e o modelo. Não substituem PIR nem escondem o conteúdo da consulta. Especificar escopo, expiração, replay, rotação de chaves, prevenção de reutilização e correlação por metadados; preferir padrões e implementações mantidas.

## 8. Transporte resiliente: QUIC, Multipath QUIC e fountain codes

### 8.1 QUIC e Multipath QUIC

QUIC/HTTP/3 pode reduzir alguns custos de conexão e evita o bloqueio de cabeça de linha entre streams independentes que ocorre com TCP multiplexado. Perda ainda pode atrasar dados dentro do mesmo stream. Multipath QUIC é uma capacidade distinta: verificar suporte real, versão do protocolo, interoperabilidade e maturidade na biblioteca escolhida; não presumir que uma biblioteca QUIC comum já oferece MP-QUIC de produção.

Medir handshake/resumption, perda, migração de caminho, congestionamento, NAT/firewalls, consumo de CPU, bateria quando relevante e latência de cauda. Definir fallback e limites contra corrida excessiva de conexões e correlação de caminhos.

### 8.2 Fountain/erasure coding

RaptorQ ou outro código de apagamento pode ser útil para transferências grandes e fragmentáveis em condições de perda. O receptor precisa receber símbolos suficientes para reconstruir os dados; há overhead de codificação e custo de CPU/memória. Não promete reconstrução instantânea nem elimina toda retransmissão.

Testar autenticação de chunks, integridade, duplicatas, limites de recursos, cancelamento, perdas em rajada e ataques de consumo de recursos.

Acompanhar a [Issue #16](https://github.com/LU9DI/AEGIS/issues/16).

## 9. Infraestrutura de nós, DHT e borda

### 9.1 DHT e conteúdo endereçado por hash

Objetos podem ser cifrados, divididos em blocos e endereçados por hashes para facilitar cache e distribuição. Definir se o hash é calculado sobre plaintext ou ciphertext; hashes de plaintext podem facilitar ataques de confirmação e deduplicação. Integridade local não garante que o objeto esteja disponível, que o peer seja honesto ou que os padrões de acesso estejam ocultos.

Avaliar manifests autenticados, rotação de chaves, revogação, disponibilidade, replicação, reparo, envenenamento de DHT e ataques Sybil/eclipse. IPs dos peers e tamanho/horário dos blocos ainda podem vazar informação.

### 9.2 WireGuard/Tailscale

Podem proteger conectividade entre nós e planos administrativos. Definir identidade dos peers, rotação de chaves, autorização de rotas e recuperação após comprometimento. Uma VPN/mesh não é automaticamente uma rede de anonimato e não esconde necessariamente endpoints e padrões de tráfego dos participantes relevantes.

### 9.3 Túnel reverso, proxy e edge computing

Cloudflare Tunnel pode ajudar a evitar exposição direta da origem; Workers, Fly.io e AWS Global Accelerator têm modelos diferentes de execução e roteamento, e não devem ser tratados como produtos intercambiáveis. Um provedor que termina o tráfego pode observar metadados e, dependendo do desenho, conteúdo.

Comparar suporte real a protocolos, regiões, cold starts, estado, custos de saída, logs, armazenamento de segredos, restrição de acesso direto à origem, dependência de fornecedor e recuperação de falhas. Não prometer latência global de milissegundos sem medições de regiões representativas.

## 10. TEEs e aceleração por hardware

TEEs como SGX, SEV-SNP e Nitro Enclaves oferecem modelos de isolamento diferentes. Atestação remota ajuda a verificar uma medição/configuração sob uma cadeia de confiança; não prova por si só que o programa nunca registra dados, não elimina canais laterais e não remove a confiança no fabricante/provedor.

Documentar atestação, pinagem de medições, atualizações, provisionamento de segredos, rollback, logs, dumps e canais laterais. Comparar com MPC/PIR e E2EE como alternativas de modelo de confiança, não como equivalentes perfeitos.

Para aceleração, medir CPU e SIMD antes de assumir que GPU/FPGA é melhor. Incluir transferência de dados, batching, fila, memória, inicialização e concorrência. Não aceitar alegações de segundos para microssegundos sem benchmarks reproduzíveis.

## 11. Minimização de dados e privacidade operacional

Inventariar identificadores, telemetria, logs e retenção. Coletar somente o necessário, usar identificadores aleatórios ou rotativos quando possível e limitar períodos de retenção. UUIDs e pseudônimos não tornam dados anônimos se houver meios de correlação.

Criar testes e revisões para evitar que tokens, consultas, chaves, endereços ou payloads sensíveis sejam registrados. Registrar também quais campos são necessários para segurança/abuso e por quanto tempo.

## 12. Interface assíncrona e confiabilidade

A interface pode usar workers, progresso, cancelamento, retries limitados e estados explícitos de pendência/erro. Ações otimistas devem ser reversíveis e locais. Uma operação sensível não deve aparecer como concluída antes de confirmação do servidor ou verificação da prova relevante.

Retries e cancelamento não podem duplicar efeitos; definir idempotência, limites, timeout e comportamento com dados obsoletos. Relacionado à [Issue #14](https://github.com/LU9DI/AEGIS/issues/14).

## 13. Matriz de avaliação e decisão

Para cada protótipo, preencher:

| Dimensão | Pergunta obrigatória |
|---|---|
| Adversário | Quem pode observar, modificar, atrasar ou combinar dados? |
| Confiança | Quais operadores, hardware e provedores precisam ser honestos? |
| Privacidade | IP, identidade, payload, índice consultado, tamanho, horário ou padrão de acesso ficam visíveis para quem? |
| Correção | Como o cliente detecta respostas fabricadas, antigas ou inconsistentes? |
| Desempenho | Qual é o custo total de cliente, servidores, comunicação e pré-processamento? |
| Disponibilidade | O que ocorre com perda de nós, partições de rede, retries e dados obsoletos? |
| Operação | Como são geridas chaves, atualizações, logs, incidentes e rollback? |
| Evidência | Há testes reproduzíveis, métricas e revisão independente? |

Não escolher tecnologia apenas por uma métrica. Comparar ameaças e custos totais.

## 14. Sequência de execução

1. **Inventário e baseline:** documentar transporte, PIR, interface, dados, deployment e medições atuais.
2. **Bloqueios de segurança:** priorizar verificação de respostas PIR e ameaças de estado/rollback antes de dados sensíveis.
3. **Experimentos isolados:** testar candidatos de PIR, MPC, cache, OHTTP e transporte sem alterar o caminho padrão.
4. **Comparação de confiança:** documentar onde MPC, TEE, OHTTP e E2EE diferem e se complementam.
5. **Protótipos com testes:** validar interoperabilidade, adversários, falhas, carga, perdas e fallback.
6. **Revisão independente:** revisar protocolo, código, dependências, implantação e resultados.
7. **Decisão explícita:** só então considerar habilitação gradual, com monitoramento, rollback e documentação.

## 15. Issues relacionadas no GitHub

- [#9 — Verificabilidade de respostas PIR sem revelar o índice](https://github.com/LU9DI/AEGIS/issues/9)
- [#13 — Avaliar PIR baseado em reticulados e medir verificabilidade](https://github.com/LU9DI/AEGIS/issues/13)
- [#14 — Prefetch, roteamento oblivious e UX assíncrona](https://github.com/LU9DI/AEGIS/issues/14)
- [#15 — MPC/PIR, TEEs, tokens cegos, DHT, E2EE e redes privadas](https://github.com/LU9DI/AEGIS/issues/15)
- [#16 — QUIC multipath, OHTTP, E2EE, erasure coding e edge](https://github.com/LU9DI/AEGIS/issues/16)
- [PR #8 — estado durável de autoridade de diretório](https://github.com/LU9DI/AEGIS/pull/8)

## 16. Estado atual e limites

Este guia consolida a arquitetura proposta e a sequência de avaliação. A inclusão de uma tecnologia neste documento ou em uma Issue não demonstra que ela foi implementada, testada, auditada ou habilitada no AEGIS. As métricas devem ser preenchidas com resultados reais; não inventar benchmarks ou alegações de anonimato.

A baseline do repositório já descreve limitações importantes, incluindo o bloqueio de PIR verificável, a hipótese de não conluio em um protótipo de PIR de duas réplicas e a ausência de garantias de produção. Essas limitações continuam valendo até serem resolvidas por código, testes e revisão.

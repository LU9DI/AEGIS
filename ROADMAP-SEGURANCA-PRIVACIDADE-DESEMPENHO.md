# AEGIS — Roadmap de Segurança, Privacidade e Desempenho

**Status:** propostas preservadas para avaliação; este documento não declara que as funcionalidades estejam implementadas.
**Escopo:** consolidar requisitos de segurança ativa, anonimato e desempenho numa lista rastreável.

## Regras de classificação
Cada item deve ser classificado como **IDEIA**, **DESENHO**, **PROTÓTIPO**, **INTEGRADO**, **TESTADO CONTRA ATAQUES** ou **VALIDADO INDEPENDENTEMENTE**. Código experimental ou testes unitários, isoladamente, não comprovam segurança de produção.

## 1. Segurança contra ataques ativos

### 1.1 Resistência à correlação de tráfego — padding adaptativo
- **Objetivo:** reduzir vazamentos por padrões de tempo, tamanho e volume observáveis entre entrada e saída.
- **Proposta:** padding adaptativo por circuito/fluxo, com distribuição aleatória documentada, limites de taxa e orçamento de tráfego; avaliar também tráfego de cobertura em períodos ociosos.
- **Limite:** padding aleatório simples não impede necessariamente correlação estatística; adversários que observam vários pontos ainda podem correlacionar padrões. Tráfego constante oferece proteção diferente, mas pode aumentar muito banda, energia e custo.
- **Validação:** experimentos com adversário definido, precisão/recall do ataque, overhead de bytes, latência, consumo e diferentes intensidades de tráfego.

### 1.2 Segurança de memória e isolamento
- **Objetivo:** reduzir corrupção de memória e falhas de isolamento em componentes críticos.
- **Proposta:** preferir Rust para novos componentes críticos quando adequado; usar tipos seguros, limites explícitos, fuzzing, auditoria de dependências e separação de privilégios.
- **Limite:** Rust reduz classes importantes de bugs de memória em código seguro, mas não elimina todos os bugs, código unsafe, falhas lógicas, dependências vulneráveis ou canais laterais. Isolamento de processo e do sistema operacional continua necessário.
- **Validação:** inventário de código unsafe, auditoria de dependências, fuzzing contínuo, testes de limites, revisão de FFI e modelo de ameaças.

### 1.3 Criptografia moderna e pós-quântica
- **Objetivo:** proteger o estabelecimento de chaves e dados em trânsito contra atacantes atuais e futuros.
- **Proposta:** avaliar ML-KEM (nome padronizado do algoritmo antes conhecido como Kyber) para encapsulamento de chaves; usar AEAD moderno, como ChaCha20-Poly1305, com nonces únicos e gestão rigorosa de chaves em cada camada.
- **Precisão:** criptografia homomórfica é uma família diferente, voltada a computar sobre dados cifrados; não é sinônimo de criptografia pós-quântica e não deve ser adicionada sem caso de uso e análise de custo. ML-KEM não substitui uma cifra de dados AEAD.
- **Validação:** biblioteca madura, formatos interoperáveis, testes vetoriais, rotação/expiração de chaves, prevenção de replay e downgrade, prevenção de reutilização de nonce e revisão independente. Avaliar modo híbrido clássico + pós-quântico durante a transição, se apropriado.

## 2. Privacidade e anonimato de ponta a ponta

### 2.1 Descoberta P2P e diretório distribuído
- **Objetivo:** evitar depender de uma única lista central de nós ativos.
- **Proposta:** avaliar DHT baseada em Kademlia com descoberta autenticada, registros assinados e de curta duração, limitação de consultas, resistência a Sybil/eclipse e mitigação de enumeração.
- **Limite:** uma DHT não é automaticamente zero-knowledge nem oculta todos os metadados. Identificadores, consultas e padrões de participação podem revelar informações; ataques Sybil, eclipse e envenenamento exigem defesas explícitas. Não afirmar que ninguém pode construir uma lista global sem demonstrar isso sob o modelo de ameaça.
- **Validação:** testes de partição, eclipse, envenenamento, enumeração, nós maliciosos e churn; medir disponibilidade e vazamentos.

### 2.2 Ofuscação de protocolo e transportes substituíveis
- **Objetivo:** dificultar classificação e bloqueio por inspeção profunda de pacotes (DPI).
- **Proposta:** arquitetura de transportes plugáveis, com especificações e testes de detecção; avaliar transportes de ofuscação existentes em vez de inventar criptografia própria. Simulação de HTTPS ou tráfego de vídeo só deve ser adotada após avaliar detecção e riscos.
- **Limite:** tráfego que apenas parece HTTPS pode ser detectado por fingerprints, comportamento ou handshake; nenhum transporte garante invisibilidade. Camuflagem não substitui criptografia nem autenticação.
- **Validação:** testes contra classificadores DPI, falsos positivos/negativos, bloqueio ativo, downgrade e censura; documentar limites por ambiente.

### 2.3 Anti-fingerprinting e proteção de metadados
- **Objetivo:** reduzir a identificação de clientes por características estáveis de pacotes, cabeçalhos e comportamento.
- **Proposta:** minimizar campos identificadores, normalizar formatos quando compatível e testar fingerprints do protocolo e do cliente.
- **Limite:** alterar cabeçalhos de aplicações indiscriminadamente pode quebrar TLS/HTTPS, autenticação ou integridade. Aplicar a proteção nas camadas controladas pelo AEGIS, sem adulterar tráfego de ponta a ponta.
- **Validação:** testes de compatibilidade e unicidade de fingerprint, além de revisão dos metadados visíveis a cada relay.

## 3. Desempenho sem comprometer o anonimato

### 3.1 Transferência multipath / múltiplos circuitos
- **Objetivo:** evitar que um único relay lento limite toda a transferência.
- **Proposta:** experimentar divisão de arquivos em blocos autenticados enviados por caminhos independentes, com reordenação, retomada e verificação de integridade no destino.
- **Limite:** múltiplos caminhos podem aumentar a superfície de correlação, expor relações entre blocos e permitir comparação de volumes/tempos. A fragmentação exige modelo de ameaça explícito e identificadores não correlacionáveis. Node.js pode orquestrar um protótipo, mas não é por si só uma garantia de segurança.
- **Validação:** throughput, latência p50/p95/p99, perda, overhead, retomada, integridade, ataques de correlação entre caminhos e comparação com um único circuito. Considerar desativação por padrão até validação.

### 3.2 Medição de largura de banda e reputação
- **Objetivo:** preferir relays capazes de entregar desempenho consistente.
- **Proposta:** desafios de capacidade com limites de recursos, amostras repetidas e reputação que decai com o tempo; tratar medições como estimativas, não provas absolutas.
- **Limite:** provas de banda podem ser falsificadas, manipuladas por colusão e favorecer operadores bem conectados; também podem criar incentivos para ataques Sybil. Pontuação não deve revelar identidade real nem conceder privilégios que enfraqueçam anonimato.
- **Validação:** resistência a inflação de métricas, replay, colusão e Sybil; justiça entre redes domésticas e centros de dados; custo de medição e impacto na seleção.

### 3.3 Seleção de circuitos baseada em latência/topologia
- **Objetivo:** reduzir latência sem abandonar o número de saltos nem as regras de anonimato.
- **Proposta:** otimizar com medições agregadas e com ruído, diversidade administrativa e limites contra concentração.
- **Limite:** escolher sempre o caminho mais rápido pode favorecer adversários próximos, facilitar inferências de localização e concentrar tráfego em poucos operadores. Distância geográfica não prevê necessariamente a rota física; latência medida pode ser manipulada.
- **Validação:** simulações adversariais, diversidade de operadores/sistemas autônomos, risco de comprometimento de múltiplos saltos, latência e vazamentos introduzidos pela medição.

## 4. Requisitos por camada

| Camada | Segurança | Privacidade | Desempenho |
|---|---|---|---|
| Entrada / Guard | Autenticação de chaves, proteção contra replay e downgrade; avaliar ML-KEM/híbrido | Transporte ofuscado; evitar revelar IP a outros relays | Latência é um sinal entre vários, nunca o único critério |
| Intermediário / Middle | Implementação segura, isolamento e dependências atualizadas | Padding adaptativo e minimização de metadados | Encaminhamento eficiente e multipath somente sob regras de privacidade validadas |
| Saída / Exit | Manter TLS ponta a ponta da aplicação; autenticar mensagens internas | Reduzir logs e fingerprinting sem alterar tráfego protegido | Medição de qualidade e limites contra abuso sem sacrificar diversidade |
| Cliente | Validar criptograficamente respostas e blocos; gestão de chaves | Não vincular blocos/circuitos com identificadores estáveis | Reassemblagem autenticada, retomada e métricas locais |
| Descoberta / DHT | Registros assinados e mitigação de Sybil/eclipse | Limitar enumeração e exposição de presença | Cache/expiração e consultas eficientes com limites |

## 5. Ordem sugerida de trabalho
1. Definir modelo de ameaça e requisitos mensuráveis para cada funcionalidade.
2. Corrigir e testar a verificabilidade de respostas PIR e outros resultados fornecidos por nós não confiáveis antes de ampliar funcionalidades.
3. Inventariar o que já existe no código e vincular cada item a arquivos, testes e evidências; não marcar itens apenas documentados como implementados.
4. Fortalecer protocolo e criptografia com bibliotecas auditadas, gestão de chaves, proteção contra replay/downgrade e revisão independente.
5. Prototipar padding e transportes ofuscados com medições explícitas de proteção e overhead.
6. Testar descoberta distribuída contra Sybil, eclipse, envenenamento e enumeração.
7. Avaliar multipath, reputação e seleção por latência em simulação adversarial antes de habilitar em produção.
8. Publicar benchmarks reprodutíveis com ambiente, baseline, scripts, percentis, banda extra, CPU/memória e relatório de limitações.

## 6. Critério de conclusão
Nenhum item será declarado concluído apenas porque existe uma classe, configuração ou teste feliz. Exigir implementação integrada, testes adversariais, regressões, benchmark quando aplicável, documentação dos metadados expostos, revisão de dependências e avaliação independente proporcional ao risco.

**Estado inicial:** todas as propostas acima são requisitos de roadmap. A existência de protótipos em outras partes do repositório deve ser verificada item a item antes de atualizar qualquer estado.


## 7. Propostas adicionais preservadas (2026-10-10)

### 7.1 Distribuição de banda estilo BitTorrent para conteúdo grande
- **Ideia:** dividir downloads grandes em blocos autenticados e permitir que vários peers/circuitos forneçam blocos em paralelo, com reassemblagem no cliente.
- **Uso apropriado:** conteúdo estático, downloads retomáveis e mídia que possa tolerar buffering; não aplicar automaticamente a cada fluxo interativo de navegação.
- **Requisitos:** manifesto de blocos autenticado, hashes/Merkle tree, validação de cada bloco, tratamento de blocos maliciosos ou duplicados, retomada, limites de memória/disco e proteção contra peers que anunciam blocos inexistentes.
- **Risco de anonimato:** peers que veem o mesmo identificador de conteúdo ou padrão de blocos podem correlacionar pedidos. Múltiplos caminhos não equivalem a anonimato mais forte; separar os circuitos pode ampliar a superfície de observação.
- **Risco de arquitetura:** peers P2P comuns não devem ser tratados automaticamente como nós de saída. O fornecimento de conteúdo deve respeitar política de saída, consentimento e o modelo de confiança.
- **Critério de sucesso:** comparar throughput útil, latência inicial, overhead, uso de CPU/RAM, resiliência à perda e resultados de testes de correlação contra o download por circuito único.

### 7.2 Canais estocásticos contra Website Fingerprinting
- **Ideia:** avaliar padding e temporização estocástica para tornar menos previsíveis os tamanhos e intervalos dos pacotes observados.
- **Requisitos:** definir distribuições e limites de overhead, aplicar padding em camadas controladas pelo protocolo e evitar que atrasos comprometam timeouts, interatividade ou controle de congestionamento.
- **Limite essencial:** ruído aleatório não torna o tráfego “impossível de classificar”. Modelos de aprendizado de máquina podem explorar padrões residuais e efeitos de ponta a ponta; atrasos de microssegundos podem ser irrelevantes em redes com jitter muito maior.
- **Critério de sucesso:** avaliar classificadores de website fingerprinting em conjuntos de treino/teste separados, incluindo ambientes diferentes e ataques adaptativos; reportar redução de precisão do atacante junto com custo de banda e latência. Não declarar imunidade sem evidência.

### 7.3 Quotas colaborativas / crédito local de prioridade
- **Ideia:** usuários que contribuem com capacidade de retransmissão saudável poderiam receber prioridade de serviço, sem moeda ou token negociável.
- **Requisitos:** definir contabilização verificável, validade e decaimento dos créditos, limites por dispositivo/identidade, prevenção de replay e abuso, e mecanismo de justiça para conexões domésticas com capacidades diferentes.
- **Risco:** reputação em DHT pode ser manipulada por identidades Sybil, conluio ou métricas falsas. A prioridade pode criar correlações entre contribuição e atividade do usuário ou concentrar tráfego nos operadores mais poderosos.
- **Princípio de privacidade:** não armazenar um histórico público e permanente de quem contribuiu, quando navegou ou quais destinos acessou. Avaliar créditos cegos ou provas limitadas de contribuição apenas se a complexidade criptográfica e o modelo de abuso justificarem.
- **Critério de sucesso:** testes contra Sybil, conluio, inflação de contribuição e discriminação de peers; medir justiça, privacidade, latência e concentração de tráfego.

### 7.4 Política de saída segura e sandbox
- **Ideia:** evitar que computadores residenciais sejam, por padrão, saídas abertas para a Internet pública. Separar a função de relay interno da função de saída.
- **Opções de arquitetura a avaliar:** (a) rede interna de serviços P2P/serviços ocultos, sem saída para a web pública; (b) saída apenas por gateways dedicados e explicitamente configurados, com isolamento, controles contra abuso e política operacional clara; (c) proxy externo opcional, apenas quando o operador tiver autorização e compreender as condições e riscos.
- **Precisão:** não prometer “risco jurídico zero”. Nenhuma arquitetura pode garantir isso; gateways, provedores, leis locais, logs, abuso e configuração afetam o risco. Proxies comerciais também deslocam confiança para o operador do proxy e podem introduzir rastreamento, custos ou termos restritivos.
- **Requisitos:** sandbox de processo/contêiner, privilégios mínimos, egress firewall, limites de taxa, isolamento entre tráfego de usuários, atualizações seguras e logs minimizados; não registrar conteúdo nem destinos além do estritamente necessário para segurança e operação.
- **Critério de sucesso:** testes de escape da sandbox, bypass de política de egress, abuso, comprometimento do gateway e documentação explícita do que cada operador pode observar.

### 7.5 Metas de arquitetura: Rust, DHT, multipath, ofuscação e quotas
As seguintes afirmações são **metas a verificar**, não fatos já comprovados sobre o AEGIS:
- núcleo crítico em Rust, com inventário claro de componentes escritos em outras linguagens;
- descoberta distribuída por DHT sem depender de uma autoridade única para toda a disponibilidade;
- transferência multipath somente para casos de uso em que blocos paralelos façam sentido e após avaliação de correlação;
- transportes ofuscados substituíveis, testados contra detecção e bloqueio ativos;
- prioridade por contribuição sem criptomoeda, com controles anti-Sybil e sem perfil público de atividade.

A comparação com Tor/I2P/BitTorrent deve ser feita por propriedade específica e versão testada. Evitar caracterizar Tor como simplesmente “arquitetura antiga” ou afirmar que DHT elimina pontos de falha: esses sistemas têm objetivos, mecanismos e compromissos diferentes.

## 8. Matriz de verificação das novas propostas

| Proposta | Evidência necessária antes de marcar como implementada |
|---|---|
| Blocos paralelos / estilo BitTorrent | Código integrado de blocos, manifesto autenticado, verificação de integridade, retomada e testes adversariais |
| Canais estocásticos | Padding e temporização realmente integrados, benchmark de website fingerprinting e relatório de overhead |
| Crédito de prioridade | Contabilidade verificável, resistência a Sybil/conluio, testes de justiça e análise de vazamento de metadados |
| Saída por sandbox/gateway | Política de egress aplicada tecnicamente, testes de escape e abuso, documentação de responsabilidades |
| Núcleo 100% Rust | Inventário de linguagens e dependências que demonstre cobertura real; não basta ter componentes Rust |
| DHT sem autoridade única | Testes de disponibilidade, eclipse, Sybil, envenenamento, enumeração e partição de rede |

**Estado das propostas desta seção:** preservadas como ideias/requisitos de roadmap. Não foram promovidas automaticamente a “implementadas”; isso exige auditoria do código, testes e evidências correspondentes.

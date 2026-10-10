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

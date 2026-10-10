# AEGIS — auditoria do GitHub e do backup

**Data da auditoria:** 2026-10-10  
**Repositório:** https://github.com/LU9DI/AEGIS  
**Branch examinada:** `main`  
**Commit examinado:** `f1e71ae4fe08cd747fe4b8bf44e77c383885fe5d`

## Resumo executivo

O ZIP consolidado publicado está presente e íntegro. O repositório Git, porém, continua sendo um **espelho parcial**: não contém os módulos e testes completos como arquivos individuais. O ZIP inclui um snapshot de pesquisa v0.27.4 que corresponde exatamente à árvore recuperada de 246 arquivos, então há um caminho para recuperar o código completo a partir dele; isso não torna a árvore de `main` completa nem transforma o protótipo em software de produção.

## O que foi verificado

- A árvore remota de `main` foi consultada pela API do GitHub: **52 arquivos** (59 entradas contando 7 diretórios), `truncated=false`.
- O commit de upload `aee4349` registra `AEGIS-consolidated-recovery-2026-10-09.zip`, com **6.177.944 bytes**.
- O Git blob SHA remoto do ZIP é `38c5c008e66466af01ad790f329b34e9b464eadd`. O mesmo SHA de objeto Git foi calculado localmente para o arquivo disponível, confirmando correspondência byte a byte com o objeto publicado.
- SHA-256 local do ZIP consolidado: `ae59e83cf68caebdebeb7522dd36c0bc16f9bbe288bbff1ce99bd7880c659be3`.
- O ZIP consolidado abre sem erro e contém 8 ZIPs de pesquisa, um Git bundle e os arquivos de status/checksum. Os 8 ZIPs internos passaram na verificação de integridade.
- O snapshot `v0.27.4-four-server-fault-detection-research.zip` tem SHA-256 `0c8e8c8e4ad49c36cea1db3c39c6a2fc53d719b98eb3d361ed5a579af51dc375`. Comparado com `current-source/` do arquivo de recuperação completo, houve **246 arquivos em cada lado, zero ausentes, zero extras e zero diferenças de conteúdo**.
- O Git bundle passou em `git bundle verify`; contém o baseline `8808fed841252ac96472a3e4babd79a3e4a906e4`. Ele preserva um baseline recuperado, não o grafo original completo de commits históricos.
- Na árvore-fonte recuperada, `python -m compileall -q src tests` passou.
- A suíte completa executada sobre a árvore-fonte recuperada terminou com **227 testes e 76 subtestes aprovados**, em 32,85 segundos.

## Lacuna entre o Git e o ZIP

O snapshot-fonte recuperado contém 42 módulos Python em `src/anonlab/` e 25 arquivos de teste. A árvore de `main` tem apenas 15 módulos de implementação e 3 arquivos de teste como arquivos individuais. Portanto, faltam no espelho Git **27 módulos Python e 22 arquivos de teste** que estão no snapshot recuperado. Isso é coerente com o README atual, que avisa que o repositório está sendo publicado incrementalmente.

O `pyproject.toml` expõe vários comandos de console cujos módulos ainda não estão presentes individualmente em `main`. Instalar/usar o projeto diretamente a partir dessa árvore parcial pode falhar para esses comandos. Use o snapshot completo dentro do ZIP se precisar da árvore-fonte integral; idealmente, publique também todos os arquivos como código normal no Git.

O arquivo de recuperação de histórico completo `AEGIS-FULL-HISTORY-RECOVERY-2026-10-09.zip` (29.923.637 bytes; SHA-256 `8b0f01c8b54e356234dab4920e228af98fe3f63b06ecbd0060906626ed7265c2`) **não é o mesmo arquivo** que o ZIP consolidado publicado. O consolidado contém snapshots selecionados; o arquivo maior reúne 458 entradas, incluindo artefatos históricos adicionais, rodas/wheels, relatórios, resultados de experimentos e inventário de checksums. Não encontrei evidência de que o arquivo de 29 MB tenha sido enviado ao repositório.

## Riscos de segurança e maturidade

1. **Não é um sistema de anonimato pronto para produção.** A documentação do próprio projeto diz que o protocolo não foi auditado, que a semântica de garlic-clove/batching não está implementada e que o testbed multi-hop permanece orientado a loopback. Não use para tráfego sensível.
2. **Falha crítica de integridade PIR conhecida:** uma réplica autenticada por TLS pode retornar uma resposta PIR falsa enquanto afirma o hash esperado do snapshot. O cliente ainda não prova que a réplica executou corretamente o cálculo. PIR verificável continua sendo trabalho de pesquisa.
3. **Colusão:** no protótipo de duas réplicas XOR-PIR, ambas as réplicas em conluio podem combinar suas máscaras e recuperar o índice consultado. A comparação de consistência de quatro servidores detecta algumas divergências, mas não é uma prova criptográfica de computação correta e não elimina falhas comuns.
4. **Sem independência operacional comprovada:** os demos RPC/TLS usam listeners no mesmo processo/host; isso não comprova segurança com operadores independentes em uma rede remota.
5. **Diretório de confiança:** a revisão documentada aponta estado de autoridade em memória e ausência de banco autoritativo de emissão para impedir que o próprio assinador emita conflitos de sequência. Verificadores podem rejeitar conflitos observados, mas isso não equivale a impedir a emissão conflitante na origem.

## Prioridades recomendadas

1. Publicar os 27 módulos e 22 arquivos de teste restantes como arquivos normais no Git e validar os comandos instaláveis a partir do checkout.
2. Atualizar o README para distinguir claramente o ZIP consolidado publicado do arquivo de recuperação completo de 29 MB.
3. Automatizar CI com testes, compilação, verificação dos manifestos/checksums e teste de instalação do pacote.
4. Manter a falha de PIR maliciosa como bloqueador de qualquer alegação de segurança/produção; especificar e implementar um protocolo de PIR verificável com análise independente antes de elevar as garantias.
5. Tratar o Git bundle como baseline recuperado; não declarar recuperado o histórico original de commits.

## Limites desta auditoria

Esta auditoria verifica a presença e integridade dos artefatos, a consistência do snapshot-fonte e a suíte automatizada. Não é uma auditoria criptográfica independente, não prova anonimato contra adversários reais e não substitui revisão de protocolo ou testes de rede multioperador.


## Correção operacional adicionada após a auditoria inicial

- Adicionado `.github/workflows/recovery-validation.yml` para verificar o SHA-256 do ZIP consolidado, testar os oito ZIPs de pesquisa internos, extrair o snapshot v0.27.4, compilar o código, instalar o pacote com o extra `onion-lab`, verificar dependências e entry points de console e executar a suíte de testes. O workflow foi ajustado para executar em todo push para `main`, em pull requests e por disparo manual.
- O checksum do ZIP consolidado foi recalculado a partir do backup de histórico completo e confirma **6.177.944 bytes** e SHA-256 `ae59e83cf68caebdebeb7522dd36c0bc16f9bbe288bbff1ce99bd7880c659be3`.
- Reexecução local independente da suíte dentro do snapshot v0.27.4: **227 testes e 76 subtestes aprovados em 32,86 segundos**, com saída normal de código 0.
- O workflow foi publicado no GitHub, mas ainda não foi possível confirmar um resultado de execução do GitHub Actions nesta auditoria. Portanto, o resultado local não deve ser confundido com um CI remoto verde.

## Acompanhamento operacional no GitHub

- Estado da branch auditada: `main` em `48dea598ba0ca66a329b14a3137dd8ac477abd6d`.
- A API de status do commit retornou `pending` sem checks registrados; **não há confirmação de CI remoto verde**.
- Ações foram registradas para evitar que as lacunas fiquem apenas no texto da auditoria:
  - [Issue #1 — publicar o snapshot-fonte como arquivos Git e validar instalação](https://github.com/LU9DI/AEGIS/issues/1).
  - [Issue #2 — corrigir a integridade PIR contra respostas falsas](https://github.com/LU9DI/AEGIS/issues/2).

## Ações ainda pendentes

A árvore Git segue parcial. A publicação dos 27 módulos Python e 22 arquivos de teste restantes como arquivos individuais não foi concluída nesta rodada. O [Issue #1](https://github.com/LU9DI/AEGIS/issues/1) acompanha a publicação, comparação do snapshot e validação de instalação. O arquivo de recuperação completo de 29 MB também continua distinto do ZIP consolidado já publicado. A falha conhecida de PIR verificável permanece um bloqueador de segurança, não corrigido por esta auditoria nem pelo workflow; o [Issue #2](https://github.com/LU9DI/AEGIS/issues/2) registra o trabalho técnico e os critérios de aceitação.


## Atualização final de recuperação — 2026-10-10

### Publicação do código e artefatos
- PR #3 foi integrado no commit `0b98818fe8e6c7472ea07ef15c55db12cab91789`: publicou como arquivos Git os módulos e testes que faltavam, documentação necessária à suíte e a proteção PIR remota fail-closed.
- PR #5 foi integrado no commit `c60d0c39722773f3ac3a29cda043a6111daf6b47`: publicou os artefatos que faltavam, incluindo changelog, relatórios, exemplos, manifests e 102 arquivos de experimento.
- A árvore de `main` após esses merges contém 42 módulos Python em `src/anonlab`, 26 arquivos de teste Python, 55 documentos Markdown em `docs`, 102 itens em `experiments` e 1 exemplo. A árvore consultada não está truncada e não contém uma cópia temporária `recovered-source/`.
- A recuperação preservou deliberadamente oito arquivos já existentes cujo conteúdo difere do snapshot, em vez de substituí-los às cegas: `docs/ARCHITECTURE.md`, `docs/MALEBOLGE_CHARTER.md`, `docs/NTOR_HANDSHAKE_EXPERIMENT.md`, `docs/TELESCOPING_EXTENSION_DESIGN.md`, `docs/THREAT_MODEL.md`, `src/anonlab/pir_rpc_demo.py`, `src/anonlab/pir_two_server.py` e `tests/test_pir_two_server.py`. A comparação e reconciliação desses arquivos continuam pendentes.

### Validação remota
- A execução de GitHub Actions do PR #3 passou: [run 38063152013](https://github.com/LU9DI/AEGIS/actions/runs/38063152013). Validou o snapshot e também o checkout Git completo, incluindo instalação do pacote, dependências, entry points, compilação e pytest.
- A execução de GitHub Actions do PR #5 passou: [run 38064033333](https://github.com/LU9DI/AEGIS/actions/runs/38064033333).
- O teste de regressão da proteção PIR elevou a suíte de 227 para **230 testes aprovados e 76 subtestes aprovados**.
- Os workflows de sincronização de recuperação falharam em tentativas intermediárias por configuração de staging/permissões de criação de PR. Esses PRs não foram mesclados com artefatos temporários; o PR #4 foi fechado como supersedido. Os PRs limpos #3 e #5 foram revisados pela suíte e mesclados.

### Segurança — mitigação, não solução criptográfica
- A API PIR remota agora falha fechada por padrão. O chamador precisa definir `allow_unverified_remote=True` para usar o modo de pesquisa sem prova, que continua inseguro e não deve receber dados sensíveis.
- Isso **não** resolve a prova criptográfica de computação correta. O protocolo verifiable-PIR com privacidade e revisão criptográfica independente continua aberto na [Issue #2](https://github.com/LU9DI/AEGIS/issues/2).
- O arquivo de recuperação histórica de 29 MB permanece distinto do ZIP consolidado publicado; o grafo original completo de commits também não foi reconstruído.
- A árvore-fonte/testes e os artefatos de pesquisa foram restaurados, mas a alegação de identidade byte a byte de todos os arquivos do snapshot não é feita até que as oito diferenças preservadas sejam revisadas.

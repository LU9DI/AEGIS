# AEGIS — auditoria do GitHub e do backup

**Data da auditoria:** 2026-10-10  
**Repositório:** https://github.com/LU9DI/AEGIS  
**Branch examinada:** `main`  
**Commit examinado:** `aee4349b675170a228cf06fb2202066e8f56526e`

## Resumo executivo

O ZIP consolidado publicado está presente e íntegro. O repositório Git, porém, continua sendo um **espelho parcial**: não contém os módulos e testes completos como arquivos individuais. O ZIP inclui um snapshot de pesquisa v0.27.4 que corresponde exatamente à árvore recuperada de 246 arquivos, então há um caminho para recuperar o código completo a partir dele; isso não torna a árvore de `main` completa nem transforma o protótipo em software de produção.

## O que foi verificado

- A árvore remota de `main` foi consultada pela API do GitHub: **50 arquivos**, `truncated=false`.
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

- Adicionado `.github/workflows/recovery-validation.yml` para verificar o SHA-256 do ZIP consolidado, testar os oito ZIPs de pesquisa internos, extrair o snapshot v0.27.4, compilar o código e executar a suíte de testes.
- O checksum do ZIP consolidado foi recalculado a partir do backup de histórico completo e confirma **6.177.944 bytes** e SHA-256 `ae59e83cf68caebdebeb7522dd36c0bc16f9bbe288bbff1ce99bd7880c659be3`.
- Reexecução local independente da suíte dentro do snapshot v0.27.4: **227 testes e 76 subtestes aprovados em 32,86 segundos**, com saída normal de código 0.
- O workflow foi publicado no GitHub, mas ainda não foi possível confirmar um resultado de execução do GitHub Actions nesta auditoria. Portanto, o resultado local não deve ser confundido com um CI remoto verde.

## Ações ainda pendentes

A árvore Git segue parcial. A publicação dos 27 módulos Python e 22 arquivos de teste restantes como arquivos individuais não foi concluída nesta rodada. O arquivo de recuperação completo de 29 MB também continua distinto do ZIP consolidado já publicado. A falha conhecida de PIR verificável permanece um bloqueador de segurança, não corrigido por esta auditoria nem pelo workflow.

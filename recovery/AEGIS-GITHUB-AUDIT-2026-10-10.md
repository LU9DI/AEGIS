# AEGIS — auditoria operacional e de segurança (atualizada)

**Data:** 2026-10-10  
**Branch:** `main`  
**Commit verificado:** `f84b0769220df94ca286904ad92a7609e668341b`  
**Repositório:** https://github.com/LU9DI/AEGIS

## Estado executivo

A recuperação operacional avançou: os módulos de código e testes foram publicados como arquivos Git, os artefatos restantes do snapshot foram incorporados pelo PR #5 e o GitHub Actions mais recente consultado concluiu com sucesso. Isso **não** significa que o AEGIS esteja pronto para produção ou que a falha criptográfica do PIR tenha sido resolvida.

- Árvore de `main` consultada pela API do GitHub: 266 entradas, 257 arquivos, sem truncamento.
- Código individual: 42 arquivos em `src/anonlab/`.
- Testes individuais: 26 arquivos em `tests/`.
- PR #5 (“Recovery: publish remaining source snapshot artifacts”): integrado; 119 arquivos adicionados.
- CI mais recente consultado: [run #28 — sucesso](https://github.com/LU9DI/AEGIS/actions/runs/38064208624), no commit acima.
- O PR #5 documentou 230 testes e 76 subtestes aprovados no snapshot recuperado e aprovação da suíte no checkout do PR.
- O status combinado de commits pode aparecer como `pending` sem status legado; para o CI atual, deve-se consultar a execução do Actions, não inferir falha a partir desse campo.

## Recuperação e integridade dos arquivos

O arquivo consolidado publicado continua sendo:
`AEGIS-consolidated-recovery-2026-10-09.zip` — 6.177.944 bytes; SHA-256 `ae59e83cf68caebdebeb7522dd36c0bc16f9bbe288bbff1ce99bd7880c659be3`.

O snapshot de código recuperado v0.27.4 tem 246 arquivos e SHA-256 `0c8e8c8e4ad49c36cea1db3c39c6a2fc53d719b98eb3d361ed5a579af51dc375`. O arquivo de recuperação de histórico completo é separado: 29.923.637 bytes; SHA-256 `8b0f01c8b54e356234dab4920e228af98fe3f63b06ecbd0060906626ed7265c2`. Não há evidência registrada de que esse ZIP maior tenha sido publicado como arquivo independente no GitHub. O Git bundle recuperado representa um baseline, não prova recuperação do grafo original completo de commits.

## Reconciliação pendente entre oito arquivos e o snapshot recuperado

A sincronização preservou deliberadamente diferenças existentes, sem sobrescrevê-las automaticamente. A comparação byte a byte dos conteúdos atuais com os arquivos do snapshot recuperado indicou diferenças nestes caminhos:

- `docs/ARCHITECTURE.md`
- `docs/MALEBOLGE_CHARTER.md`
- `docs/NTOR_HANDSHAKE_EXPERIMENT.md`
- `docs/TELESCOPING_EXTENSION_DESIGN.md`
- `docs/THREAT_MODEL.md`
- `src/anonlab/pir_rpc_demo.py`
- `src/anonlab/pir_two_server.py`
- `tests/test_pir_two_server.py`

Essas diferenças não são automaticamente defeitos: alguns arquivos atuais contêm esclarecimentos e proteções mais recentes, e o módulo PIR atual documenta limites e validações adicionais. Mas cada diferença precisa de uma decisão explícita (manter versão atual, incorporar alterações do snapshot, ou mesclar manualmente), seguida de testes. Não se deve substituir código de segurança atual apenas para obter igualdade de hashes.

A issue #1 continua aberta até a reconciliação das oito diferenças e a verificação final do inventário. O ZIP de histórico completo também deve continuar identificado como artefato separado, sem alegar que está no repositório.

## PIR: mitigação implementada, falha criptográfica ainda aberta

O endpoint RPC remoto de duas e quatro réplicas é recusado por padrão quando a computação não pode ser verificada criptograficamente. A opção explícita `allow_unverified_remote=True` existe apenas para pesquisa controlada e não torna a operação segura. O teste `tests/test_pir_remote_fail_closed.py` cobre a rejeição antes de I/O de rede.

O módulo `src/anonlab/pir_commitment.py` oferece compromissos Merkle e provas de inclusão de registros, mas **não** prova a correção de uma resposta PIR e revela o índice do registro. Não deve ser conectado diretamente ao caminho PIR privado. Os manifests assinados autenticam metadados do snapshot, não provam que a réplica calculou a resposta corretamente.

Consequências e limitações:
1. TLS autentica o endpoint e protege o canal, mas não prova a computação correta.
2. Duas réplicas XOR-PIR em conluio podem recuperar o índice consultado.
3. Comparação entre quatro respostas detecta algumas divergências, mas não elimina conluio ou falhas comuns e não constitui prova criptográfica.
4. A mitigação atual é fail-closed por padrão, não uma solução de PIR verificável.

A issue #2 permanece um bloqueador. Para encerrá-la, é necessário selecionar uma construção criptográfica apropriada que preserve a privacidade do índice, formalizar a declaração provada e as hipóteses, integrar uma implementação madura, testar adulteração/replay/snapshot obsoleto, medir custos e obter revisão criptográfica independente. Não é seguro inventar uma prova caseira ou apresentar um hash assinado como prova de execução correta.

## Outras limitações de maturidade

- O projeto permanece protótipo de pesquisa, não um sistema de anonimato pronto para tráfego sensível.
- Os demos multi-hop e RPC não demonstram operação robusta entre hosts e operadores independentes na Internet.
- A semântica completa de garlic-clove/batching, proteção contra correlação de tráfego em adversários reais e revisão independente do protocolo continuam sem comprovação suficiente.
- O diretório de confiança e a persistência/serialização autoritativa de emissão de credenciais precisam de validação além dos testes de simulação.

## Próximas ações obrigatórias

1. Revisar individualmente as oito diferenças preservadas e registrar a decisão de cada arquivo.
2. Executar CI após a reconciliação e verificar instalação, entry points, compilação e testes no checkout.
3. Manter o acesso PIR remoto bloqueado por padrão até haver verificação criptográfica real; não usar o modo de pesquisa com dados sensíveis.
4. Manter explícita a diferença entre ZIP consolidado e ZIP de recuperação histórica.
5. Não anunciar anonimato, resistência a observador global ou PIR verificável sem evidências e revisão independente.

**Conclusão:** a recuperação do código e a validação de CI avançaram, mas ainda existem pendências de reconciliação e segurança criptográfica. Esta auditoria não equivale a uma auditoria criptográfica independente.


## Atualização pós-PR #6 (2026-10-10)

O PR #6 foi integrado no commit `a1ed52e7dc9bd3b931fa7b92b1cc853c1062f92e`. A API RPC agora rejeita toda recuperação PIR não-loopback, mesmo se o parâmetro legado de pesquisa for definido, até existir prova criptográfica real de computação. Foram adicionados testes para bypass, host e hostname. A validação do PR passou em https://github.com/LU9DI/AEGIS/actions/runs/38067810483: 233 testes e 76 subtestes no checkout e 230 testes e 76 subtestes no snapshot recuperado. A issue #2 permanece aberta: esta mudança é mitigação, não prova verificável de PIR. As oito diferenças de arquivos preservadas continuam pendentes de reconciliação manual.
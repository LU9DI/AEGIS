# AEGIS — estado durável da autoridade de diretório

## Implementação submetida na PR #8

A implementação faz `DirectoryAuthority` aceitar `state_path` para registrar emissão em SQLite. `BEGIN IMMEDIATE` serializa escritores entre processos; o banco é vinculado ao fingerprint SHA-256 da chave pública da autoridade. Cada relay tem uma sequência atual, digest do descritor certificado e serial histórico único. Sequências menores são rejeitadas, repetição idempotente do mesmo descritor na mesma sequência é aceita, e conteúdo diferente com a mesma sequência é rejeitado. A reserva é confirmada antes de devolver o certificado.

A autoridade persistente também registra snapshots assinados de revogação por epoch. Repetir o mesmo epoch e a mesma lista devolve o snapshot original; alterações no mesmo epoch, rollback de epoch e remoção de revogações anteriores são rejeitados. Os snapshots são assinados e armazenados na mesma base SQLite, em transações serializadas.

## Defesa adicional contra perda de metadados

A inicialização agora falha de forma fechada se o fingerprint da chave da autoridade estiver ausente enquanto existirem registros de emissão ou snapshots de revogação. Isso impede que a remoção isolada da linha de metadados re-vincule silenciosamente um banco populado a outra chave. O teste `test_durable_authority_fails_closed_if_key_fingerprint_is_deleted` cobre esse cenário; a execução CI 38074693655 terminou com sucesso no commit `a5b0c71b1a89fde0e14ecf41a721167db8f86a25`.

## Limitações explícitas

- O modo sem `state_path` permanece por compatibilidade com demos antigas; não é autoridade durável e não deve ser usado como autoridade numa rede real.
- SQLite local não evita rollback se alguém restaurar uma cópia antiga do banco, nem protege contra comprometimento do host ou da chave privada.
- Emissão de descritores e publicação de revogações usam transações duráveis separadas. A integridade de cada registro é protegida, mas ainda não existe uma transação de protocolo que faça as duas operações avançarem em conjunto.
- A verificação criptográfica da correção do PIR permanece uma lacuna independente e bloqueadora para uso sensível.
- Esta alteração precisa passar pelo CI completo e por revisão independente antes de qualquer alegação de prontidão operacional.


## Revisão adicional de segurança do caminho SQLite

A revisão estática do commit atual identificou um hardening pendente no tratamento do arquivo de estado:

- A checagem Path.is_symlink() ocorre antes de sqlite3.connect(). Se um agente hostil puder modificar o diretório pai durante essa janela, a checagem e a abertura não são atômicas (risco TOCTOU).
- O arquivo é colocado em modo 0600 com chmod somente depois de a conexão SQLite abrir/criar o arquivo. Portanto, numa criação nova, as permissões iniciais dependem do umask e podem ficar mais permissivas por um intervalo curto.
- A permissão do diretório pai não é validada. A proteção contra troca de caminho depende, portanto, de o diretório que contém o banco não ser gravável por um atacante.

**Estado:** achado de revisão estática, ainda não corrigido nem validado por teste. A PR não deve ser tratada como hardening completo para um ambiente multiusuário hostil até resolver a abertura segura do arquivo, a criação com permissões restritas desde o primeiro instante e testes de regressão adequados. O teste existente que rejeita um symlink cobre o caso estático, não a corrida TOCTOU.

Esse achado não altera o resultado do CI existente: o workflow testa o código submetido, mas não comprova ausência desse tipo de corrida. Também não resolve o rollback por restauração de backup antigo, que exige uma âncora monotônica externa ou testemunhas independentes.


## Mitigação implementada na revisão seguinte

Após registrar o achado, a implementação foi endurecida na branch desta PR:

- Em POSIX, o diretório que contém o estado deve pertencer ao usuário efetivo e não pode ser gravável por grupo/outros.
- O banco é aberto primeiro com `os.open`, `O_NOFOLLOW` quando disponível, `O_CLOEXEC` quando disponível e modo de criação `0600`; o descritor é validado como arquivo regular e as permissões são aplicadas via `fchmod` antes da abertura SQLite.
- O teste de symlink existente foi preservado e foi adicionado `test_durable_authority_rejects_group_or_world_writable_state_directory`.

**Validação ainda pendente:** no momento deste registro, as execuções CI para os commits que contêm o hardening e o teste estão em andamento/fila. Não considerar a mitigação validada até o workflow do HEAD mais recente terminar com sucesso. A proteção reduz a exposição a troca do caminho por outros usuários locais, mas não protege contra processos maliciosos executados sob o mesmo UID, comprometimento do host ou rollback do arquivo por backup antigo.


A revisão também adicionou rejeição explícita de arquivos de estado com mais de um hard link (`st_nlink != 1`) e o teste `test_durable_authority_rejects_hard_linked_state_file`, para evitar que a aplicação altere um arquivo externo compartilhando o mesmo inode. O HEAD agora inclui esse teste; a execução CI correspondente ainda precisa terminar para validar a alteração integrada.


## Atualização final da validação — 2026-10-10

A validação do HEAD f227857c67e55b741ba3430cdce6ac1eb1d43c44 terminou com sucesso:

- Workflow: [Recovery archive validation, execução 38076779021](https://github.com/LU9DI/AEGIS/actions/runs/38076779021).
- Todas as etapas executadas terminaram com sucesso, incluindo compilação, instalação e verificação de dependências, validação de entry points, suíte de testes da fonte recuperada e validação da árvore Git.
- A execução anterior no commit a2d881e634a4e1b053c07c9eaaff0003b6158e58, que incluiu o teste de hard links, também terminou com sucesso.

Este resultado substitui as notas anteriores que diziam que o CI estava pendente. É evidência de que o workflow passou no HEAD; não é uma prova formal de ausência de vulnerabilidades.

## Riscos residuais após o hardening

A abertura SQLite ainda valida o diretório pai por caminho e depois abre o banco por caminho. A proteção de diretório privado reduz a possibilidade de troca por outro usuário local, mas não é uma garantia geral contra manipulação de ancestrais de caminho, processos sob o mesmo UID ou comprometimento do host. Uma defesa mais forte pode usar abertura relativa a descritores de diretório (openat/dir_fd) e validar a cadeia de diretórios; deve ser implementada de forma portátil e coberta por testes antes de alegar proteção contra um adversário local forte.

Permanecem bloqueadores de arquitetura: rollback por restauração de uma cópia antiga do SQLite sem âncora monotônica externa, protocolo transacional conjunto para emissão e revogação, e verificabilidade criptográfica da correção de respostas PIR. A PR permanece draft e não deve ser descrita como pronta para produção ou como auditoria de segurança concluída.


## Acompanhamento de hardening de caminhos

O risco residual de manipulação de diretórios ancestrais e corridas sob o mesmo UID foi registrado para trabalho separado na [issue #10](https://github.com/LU9DI/AEGIS/issues/10). A issue exige modelo de ameaça explícito, abertura relativa a descritores de diretório quando suportada, testes adversariais de troca de caminho e validação completa no CI. Até esse trabalho ser implementado e revisado, a proteção atual deve ser descrita como mitigação limitada, não como abertura totalmente livre de corridas.


## Confirmação CI no HEAD atual — 2026-10-10

Após as atualizações de documentação acima, o workflow **Recovery archive validation** também terminou com sucesso no HEAD `2e914acbc7de68fc5de6fd459642c60e1a24a184`: [execução 38077424279](https://github.com/LU9DI/AEGIS/actions/runs/38077424279).

O job `recovered-source` concluiu com sucesso a verificação de checksum/integridade do ZIP, compilação da fonte recuperada e testes, instalação/verificação de dependências, validação de entry points e verificação da árvore Git. Etapas de recuperação/publicação de arquivos foram corretamente ignoradas por não serem necessárias neste PR.

Isso valida o workflow automatizado neste commit, não a ausência de corridas TOCTOU, rollback por restauração de backup, nem a segurança do protocolo PIR. A PR segue aberta como draft; os bloqueadores arquiteturais e a revisão independente continuam pendentes.

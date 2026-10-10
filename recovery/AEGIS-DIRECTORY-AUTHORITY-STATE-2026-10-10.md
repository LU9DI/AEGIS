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

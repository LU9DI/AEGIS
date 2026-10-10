# AEGIS — estado durável da autoridade de diretório

## Implementação submetida na PR #8

A implementação na PR #8 faz DirectoryAuthority aceitar state_path para registrar emissão em SQLite. A transação BEGIN IMMEDIATE serializa emissores concorrentes entre processos; o banco é vinculado ao fingerprint SHA-256 da chave pública da autoridade. Cada relay tem uma sequência atual, digest do descritor certificado e serial único. Sequências menores são rejeitadas, repetição idempotente na mesma sequência é aceita, e conteúdo diferente com a mesma sequência é rejeitado. A reserva é confirmada antes de devolver o certificado.

## Limitações explícitas

- O modo sem state_path permanece apenas por compatibilidade com demos antigas; não é autoridade durável e não deve ser usado em uma rede real.
- SQLite local não evita rollback se alguém restaurar uma cópia antiga do banco, nem protege contra comprometimento do host ou da chave privada.
- A publicação de revogações ainda não compartilha transação/epoch com o registro de emissão. Isso permanece uma lacuna independente.
- A mudança precisa passar pelo CI completo e revisão independente antes de qualquer alegação de prontidão operacional.

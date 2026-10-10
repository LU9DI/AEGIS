# AEGIS v0.27 — revisão de construções para PIR verificável

**Status:** decisão técnica preliminar; não é implementação criptográfica nem aprovação para produção.  
**Escopo:** escolher um caminho de pesquisa que impeça uma réplica autenticada de falsificar uma resposta PIR sem revelar o índice consultado.

## Decisão executiva

**Não ativar respostas PIR remotas como verificadas. Não adicionar provas Merkle de inclusão ao caminho privado. Não escrever um verificador substituto/mock.**

A próxima etapa deve ser um protótipo isolado de prova de computação sobre um snapshot imutável, acompanhado de uma comparação reproduzível de custos. A família de prova (SNARK/STARK ou outra prova sucinta de computação) ainda não deve ser escolhida por nome ou popularidade: primeiro precisamos de uma declaração formal da relação que será provada e de medições sobre dados representativos. O sistema atual usa XOR byte a byte; não é válido presumir que uma commitment aditiva genérica preserve automaticamente essa semântica.

## Relação a provar

Para um snapshot autorizado D = (D[0], ..., D[N-1]), cada registro de largura fixa W, raiz/identificador R, epoch e e máscara canônica q:

- R compromete exatamente os bytes canônicos de todos os registros, a ordem, N, W, o esquema e a versão do protocolo;
- q tem exatamente ceil(N/8) bytes e os bits de padding não utilizados são zero;
- y = XOR(D[i] para cada i em que q[i] = 1);
- a prova está vinculada a R, e, N, W, q, y e à versão do protocolo;
- a prova não revela registros não selecionados nem a máscara do outro servidor;
- uma resposta ou prova de outra máscara, raiz, epoch, dimensão ou versão deve falhar.

A máscara é conhecida pela própria réplica que responde; o objetivo não é escondê-la dessa réplica, e sim não revelar o índice-alvo através da máscara individual, da prova ou do transcript. A privacidade do protocolo de duas réplicas continua dependendo de não haver conluio entre elas.

## Comparação de famílias

| Família | O que pode oferecer | Risco/gargalo específico do AEGIS | Decisão atual |
|---|---|---|---|
| Prova sucinta de computação (por exemplo, SNARK/STARK) | Provar que y é o resultado da relação definida sobre o snapshot comprometido | A relação precisa verificar o compromisso e a seleção/XOR; custo de provar sobre muitos registros pode dominar a latência; setup, memória e tamanho de prova variam muito | **Primeiro protótipo de referência**, sem prometer desempenho |
| Compromisso vetorial/polinomial com prova de consulta linear | Pode reduzir o custo de prova quando a álgebra da consulta corresponde à construção | XOR byte a byte não é automaticamente uma operação linear no campo de compromisso; exige codificação bit a bit, restrições Booleanas ou uma construção especializada, com análise de soundness e binding | Pesquisar em paralelo; não integrar até provar compatibilidade algébrica |
| Merkle inclusion proof | Prova que um registro específico pertence à raiz | Revela o índice e não prova que a resposta XOR da réplica foi calculada corretamente | **Rejeitada para o caminho PIR privado** |
| Maioria, redundância, spot checks ou assinaturas do snapshot | Podem ajudar disponibilidade ou detectar algumas classes de falhas | Não constituem, por si sós, prova de computação correta contra uma réplica maliciosa; maioria pode compartilhar falhas ou conluio | Defesa auxiliar, nunca rotular como PIR verificável |
| PIR computacional baseado em criptografia homomórfica | Pode mudar o modelo de confiança e o formato de consulta/resposta | É uma mudança de protocolo, com custo criptográfico e requisitos de prova de correção separados; não é drop-in para o XOR de duas réplicas | Alternativa de arquitetura a comparar, não presumir compatibilidade |

## Critérios eliminatórios

Uma proposta é rejeitada se qualquer item ocorrer:

1. O índice-alvo é revelado à réplica ou ao verificador além do vazamento expressamente declarado.
2. O cliente precisa confiar na afirmação da própria réplica de que sua prova é válida.
3. A prova não vincula raiz autorizada, epoch, dimensões, máscara exata, resposta e versão do protocolo.
4. Um snapshot antigo pode ser aceito silenciosamente ou os dois servidores podem responder por epochs incompatíveis.
5. O código aceita resposta sem prova, prova ausente, erro do verificador ou fallback não verificado como sucesso.
6. A segurança depende de um verificador mock, de testes apenas, de hashes assinados sem prova de computação, ou de Merkle inclusion proof que revela o índice.
7. A implementação não possui testes de adulteração e limites de recursos para provas malformadas/oversized.

## Plano de avaliação reproduzível

Para cada candidato, registrar commit, versão e configuração de bibliotecas, hardware, sistema operacional, parâmetros criptográficos e pressupostos de setup.

Medições mínimas:
- tamanhos de snapshot (pequeno, médio e grande) e larguras de registro representativas;
- tempo de geração da prova, p50/p95/p99 de verificação, pico de memória;
- bytes de consulta, resposta e prova; throughput sob concorrência;
- custo de criação/atualização do compromisso;
- execução fria e aquecida, número de repetições, dispersão e falhas;
- comparação com o PIR XOR atual, sem confundir comparação de laboratório com melhoria de produção.

## Testes adversariais obrigatórios

- resposta honesta e snapshot autorizado: aceita;
- alteração de um bit na resposta: rejeita;
- prova de outra máscara, raiz, epoch, largura, contagem ou versão: rejeita;
- replay de resposta/prova em nova requisição: rejeita;
- prova truncada, inválida, não canônica ou acima do limite: rejeita dentro de orçamento de recursos;
- snapshot antigo ou divergência entre réplicas: falha fechada;
- erros/logs não expõem índice-alvo, máscaras, conteúdo de registros nem identificadores estáveis por consulta;
- teste estatístico do transcript para verificar que a distribuição observável por uma única réplica não depende do índice-alvo.

## Marcos e gates

1. Formalizar a relação e os bytes canônicos do snapshot.
2. Criar protótipo isolado de prova de computação e benchmark; sem integração no caminho remoto.
3. Comparar a opção vetorial/polinomial e documentar por que a álgebra escolhida prova exatamente a operação XOR requerida.
4. Fazer revisão criptográfica independente da relação, compromisso, soundness, binding e vazamentos.
5. Integrar apenas se os testes de adulteração passarem e os custos forem aceitáveis; caso contrário, manter o modo remoto bloqueado/fail-closed.

## Conclusão

O estado atual continua **PIR experimental não verificável**. TLS autentica o endpoint e protege o transporte; assinaturas autenticam metadados; Merkle prova inclusão. Nenhum desses elementos isoladamente prova que a réplica calculou a resposta correta. Nenhuma alteração neste documento muda essa classificação.

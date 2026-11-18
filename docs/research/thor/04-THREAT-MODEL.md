# 04 — Modelo de ameaças e critérios de avaliação de privacidade

- **Alvo**: o AEGIS como protótipo de rede de baixa latência; a comparação é com o Tor, não com "um proxy".
- **Regra**: este documento define o que precisa ser provado, quais adversários importam e o que o código atual **não** prova. Nada aqui certifica anonimato.
- **Estado**: a §4 lista o que existe hoje no repositório e por que isso não sustenta qualquer alegação de paridade com o Tor. A §5 define o protocolo de avaliação que falta executar; a §6 define critérios de aceitação e de falsificação.

## 1. Ativos, metadados e o que é protegido

| Ativo | Protegido por | Vaza para | Não é protegido |
|---|---|---|---|
| Conteúdo do payload | AEAD por hop (ChaCha20-Poly1305); TLS opcional no PIR | ninguém além do destino (se o AEAD estiver correto) | — |
| Destino final | camadas onion: só o exit parseia o destino (`telescoping.py:1040-1058`) | exit | exit sempre sabe o destino |
| Identidade do cliente | nenhuma autenticação de cliente no caminho (`_link_hello` modo 0, `telescoping.py:320-331`) | guarda (IP, tempo, volume) | IP de entrada é sempre visível ao guarda |
| Posição no caminho | relays veem apenas o hop seguinte (`allowed_next_port`) | guarda/middle/exit veem topologia parcial | conluio de hops reconstrói o caminho |
| Tempo e volume | **nada** no caminho de dados | guarda, exit, observador local, observador global | é o metadado central de correlação |
| Sequência de direções/tamanhos | AEAD esconde conteúdo; tamanhos externos não são normalizados | observador local | é a base de website fingerprinting |
| Ciclo de vida do circuito | limites de conexão/tempo (`DEFAULT_MAX_ACTIVE_CONNECTIONS`, `MAX_ACTIVE_STREAMS`) | observador local | padrões de conexão são distinguíveis |

Consequência: o AEGIS hoje esconde **conteúdo** e **parcialmente topologia**; não esconde **tempo**, **volume**, **tamanhos** nem **ciclo de vida**. Como qualquer defesa séria de WF/correlação depende desses quatro últimos, não existe hoje defesa de anonimato comparável à do Tor — o Tor tem cellização fixa (512 B), padding de circuito (limitado, ver `02`) e uma rede de guards com entrada pública. O AEGIS não tem nenhum dos três.

## 2. Adversários explícitos

Cada adversário tem capacidades, o que pode observar, o que o AEGIS faz hoje e o experimento que o mede. "Hoje" significa no commit base `d8b84d5`.

**A1 — Observador local / ISP.** Capacidades: vê todo o tráfego do enlace de acesso do cliente, sem criptografia do nível de transporte (o AEGIS não usa TLS entre cliente e guarda). Observa: IP do guarda, tempo, volume, direção, tamanhos. Hoje: nada é escondido; a única mitificação é o AEAD dentro do TCP, que não muda tamanhos. Experimento: correlação tempo/volume e fingerprinting de direção sobre o enlace cliente↔guarda.

**A2 — Relay malicioso único.** Capacidades: controla guarda, middle ou exit; executa o protocolo corretamente e registra o que parseia. Observa: no guarda, IP do cliente, primeiro comando, `next_port`; no exit, destino e payload. Hoje: `RelayObservation` registra apenas operação e porta, sem payload (`telescoping.py:1034,1047`); o exit por desenho vê o destino. Experimento: quantas posições são necessárias para ligar entrada e saída; simulação de conluio parcial.

**A3 — Observador de entrada e saída (two-point).** Capacidades: vê o enlace do cliente e o enlace do exit/destino. Observa: séries temporais de bytes. Hoje: o simulador calcula correlação de Pearson com lag máximo (`simulator.py:109-132`) — um atacante deliberadamente fraco, sobre dados sintéticos. Experimento: correlação com atacantes melhores (cross-correlation normalizada, mutirão de *detection theory* com TPR@FPR=1%), e com padding/cover sob orçamento de banda.

**A4 — Correlação temporal e volumétrica.** Capacidades: A3 com janela longa e múltiplas amostras. Observa: volume agregado, rajadas, pausas. Hoje: não há padding nem cover no caminho de dados; qualquer correlação é essencialmente direta. Experimento: AUC / TPR@FPR por defesa, com e sem cover de taxa constante, cobrando o custo de banda.

**A5 — Website fingerprinting.** Capacidades: observa apenas a sequência de direções/tamanhos/intervalos do cliente ao guarda (como um WF clássico sobre Tor). Hoje: o avaliador implementa **apenas** centroide mais próximo sobre histogramas sem ordem (`privacy_eval.py:143-164,216-259`), com embaralhamento que destrói a ordem dos pacotes (`privacy_eval.py:116-118`); acurácia 1,0 em dados "plain" e "padded" no artefato não versionado `experiments/privacy-eval.json` — ou seja, o experimento não demonstra defesa alguma. Experimento: atacantes fortes (k-NN k-FP com features ponderadas de direção cumulativa; regressão logística; CNN 1D sobre sequência de direções), split group-disjoint por instância de site, múltiplas seeds, mundo aberto com classe desconhecida, e métricas de detecção (TPR@FPR fixo, AUC).

**A6 — Comprometimento de relays (Sybil/colusão).** Capacidades: controla k de n relays e seleciona posições. Observa: tudo que os relays veem. Hoje: seleção de rota geométrica com restrições de ASN/família/sub-rede (`route_selection.py`), sem prova de resistência a Sybil; `docs/THREAT_MODEL.md:53` já declara que a seleção é heurística local. Experimento: probabilidade de comprometer guarda+exit em função de fração de relays comprometidos, com e sem pinning de guarda.

**A7 — Ataques de congestionamento e manipulação de tráfego.** Capacidades: injeta fila/perda em um relay para criar um sinal distinguível (Sniper/DeepCorr/ataques de congestão). Observa: mudanças de RTT/throughput. Hoje: sem CC nem pacing próprios; sem defesa. Experimento: sinal de congestão em um hop controlado vs linha de base, com e sem cover.

**A8 — Adversário global passivo.** Capacidades: vê muitos enlaces. Hoje: explicitamente não defendido (`docs/THREAT_MODEL.md:26`). Experimento: nenhum — deve permanecer como não-alegação.

## 3. Suposições de confiança (declaradas, não provadas)

1. O AEAD ChaCha20-Poly1305 (`cryptography`) é seguro; o nonce é aleatório de 12 bytes por mensagem (`onion_protocol.py:83-95`), o que evita reúso desde que a chave não seja reutilizada entre circuitos.
2. O handshake ntor-derived e o KDF MALEBOLGE **não** têm revisão independente (`docs/THREAT_MODEL.md:23`); qualquer alegação de segurança de chave é condicional a essa revisão.
3. Descritores e autorização por diretório são confiáveis quando o verificador é configurado; no harness, descritores são objetos em memória.
4. Pelo menos um relay honesto no caminho; pelo menos um ponto honesto na rede de guards (não implementada).
5. O atacante não controla a origem nem o destino simultaneamente com o relay da mesma posição (exceto nos cenários declarados de colusão).
6. O cliente não vaza identidade por fora do protocolo (DNS, browser, aplicação) — nada no AEGIS impede isso hoje; é pré-requisito de qualquer medição de anonimato.

## 4. O que o repositório mede hoje e por que não basta

- **Atacante único e fraco**: centroide mais próximo, features sem ordem, closed-world, uma seed, sem IC.
- **Estratificação por classe no split sintético** (`privacy_eval.py:167-194`): não há `group_id` no gerador sintético, então não é group-disjoint.
- **Defesa que não muda a acurácia**: o relatório de sweep mostra defesa sem efeito mensurável (`experiments/PRIVACY-EVAL-SWEEP-REPORT.md`), o que é um resultado válido — desde que não seja apresentado como "defesa".
- **Artefato não versionado** `experiments/privacy-eval.json`: schema 1 (o HEAD emite schema 2), `accuracy` 1,0 em plain e padded, sem commit/ambiente/linha de comando. **Não é evidência** e não deve ser citado.
- **Simulador** mede correlação de volume com um atacante explicitamente limitado (`simulator.py:114-115`).
- **Zero traces reais**: nenhum pcap, nenhum corpus de sites, nenhuma topologia real.

Conclusão: hoje o repositório **não pode** afirmar nada sobre privacidade comparada ao Tor, e o próprio código diz isso. Este documento não muda essa conclusão; ele define o que seria necessário para mudá-la.

## 5. Protocolo de avaliação a executar (definição, não resultado)

Requisitos mínimos para qualquer alegação futura:

1. **Dados com proveniência**: traces reais (pcaps de um corpus público como os usados em WF) ou, no mínimo, gerador sintético determinístico com `group_id` explícito por instância de site, versão do gerador e digest do arquivo. Dados sintéticos só sustentam conclusões sobre o gerador.
2. **Split group-disjoint** por instância/sessão, não por trace; nenhum grupo em treino e teste.
3. **Múltiplas seeds** (≥5) para treino/teste; reportar mediana e IC bootstrap; nunca um único número.
4. **Atacantes fortes** no mesmo orçamento de computação: k-NN k-FP, regressão logística, CNN 1D (DF-lite) e, quando viável, DF completo; o adversário do AEGIS e o do Tor recebem os mesmos dados, features e budget.
5. **Mundo aberto**: classe desconhecida + taxa de falso positivo; métricas TPR@FPR=1%/0.1%, AUC, precisão/recall — não apenas acurácia closed-world.
6. **Comparação pareada com o Tor**: mesmos sites, mesmas janelas, mesmos recursos, mesmo atacante; reportar diferença de acurácia com IC, não "AEGIS é melhor".
7. **Custo da defesa**: para cada defesa (padding/cover), reportar banda extra, latência adicional e p95 de transferência — a meta de 90% é medida junto, não depois.
8. **Reprodutibilidade**: commit, seed, ambiente, digest do dataset e comando, como no harness de desempenho (`src/anonlab/thor_lab`).

## 6. Critérios de aceitação e de falsificação

A meta da missão é "privacidade e anonimato iguais ou superiores aos do Tor sob modelos comparáveis". Traduzindo para testes falsificáveis:

- **C1 (não-pior)**: em cada adversário A3–A7, a acurácia/AUC do atacante contra o AEGIS não pode ser estatisticamente maior que contra o Tor, com IC de 95% e mesma seed/traces.
- **C2 (orçamento)**: o custo de defesa do AEGIS não pode exceder o do Tor em banda e latência para o mesmo nível de resistência.
- **C3 (desempenho)**: goodput AEGIS ≥ 90% da Surface no tier correspondente, com IC e n≥5.
- **Falsificação**: se qualquer C1 falhar com IC de 95% e o efeito não for explicado por falta de dados, a alegação de paridade cai. Se C3 falhar, a meta de desempenho não está atingida — sem reinterpretação.

Hoje: C1 não é mensurável (sem traces reais, sem avaliador forte); C2 não é mensurável (sem padding implementado); C3 é mensurável apenas no tier lab e está em ~10–19% (`06-LAB-RESULTS.md`). Portanto, **nenhuma alegação de paridade com o Tor é sustentável nesta entrega**, e o relatório de resultados deve dizer exatamente isso.

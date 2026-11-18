# 07 — Resultados medidos: tier público (Surface × Tor real)

- **Artefatos**: `experiments/thor-lab/public-01/` e `experiments/thor-lab/public-02/` (duas execuções independentes, seeds `20261118` e `20261119`).
- **Revisão do código**: `1aa9130539a30c7ab7c62f116b4fa8771709c584` (`dirty: false`).
- **Tor**: expert bundle oficial `tor-expert-bundle-windows-x86_64-16.0.1.tar.gz` (SHA-256 do arquivo `9eed3c3ff1fe43df034ce360196c9ec95472560d77ff55614d0cd5120edea27b`; `tor.exe` `da22856f95ee24f8ace4ad1ab04acbd818fd6c3042bc3cf8f1d7cc3fa3edcb2b`), executado localmente com `SocksPort 127.0.0.1:9050`, bootstrap 100%.
- **Alvo**: `http://cachefly.cachefly.net/1mb.test` com `Range: bytes=0-262143` (256 KiB), o mesmo alvo e o mesmo pedido para os dois braços.
- **Workload**: uma requisição HTTP/1.1 por trial; 5 trials + 1 warmup por braço; 0 erros, 0 falhas de integridade.
- **O que este tier NÃO é**: o AEGIS **não participa** deste tier (transporte loopback-only, `01` F7). Aqui só se mede a linha de base real Surface × Tor nesta máquina/enlace.

## 1. Resultados

### Run 1 (`public-01`, seed 20261118, `trials.jsonl` SHA-256 `ced15accc8fa926ededcdae7d765e11b9cbf5a24238c0d3b0c2a0d2d7c838b11`)

| Braço | n | Goodput Mb/s (p50 [IC 95%]) | TTFB p50 ms | Conclusão p50 / p95 ms | Setup p50 ms | Fio ↓ (×payload) | CPU (1 núcleo) | RSS pico MiB |
|---|---|---|---|---|---|---|---|---|
| `surface` | 5 | 5,95 [0,83; 17,74] | 136,32 | 352,54 / 2 504,59 | 1,37 | 1,002 | 0,000 | 32,4 |
| `tor_socks` | 5 | 1,58 [1,20; 2,31] | 324,57 | 1 326,09 / 1 682,99 | 330,42 | 1,002 | 0,019 | 32,5 |

Ratio pareado (mediana): **0,217** [0,130; 1,858]. Ratios por trial: 0,201 / **1,804** / **1,858** / 0,217 / 0,130 — em dois dos cinco trials o Tor foi *mais rápido* que a Surface, porque a Surface sofreu pausas de ~2,5 s no enlace de acesso. Taxa de conclusão pareada (Tor/Surface): mediana 5,96× [0,67; 10,07] — o IC inclui 1,0, coerente com a instabilidade acima.

### Run 2 (`public-02`, seed 20261119, `trials.jsonl` SHA-256 `46f6a6fcb2b1aa7a217d4dcf38591d2bc7aa3faeba23950fa41a53b79490c6a4`)

| Braço | n | Goodput Mb/s (p50 [IC 95%]) | TTFB p50 ms | Conclusão p50 / p95 ms | Setup p50 ms | CPU (1 núcleo) | RSS pico MiB |
|---|---|---|---|---|---|---|---|
| `surface` | 5 | 11,91 [0,65; 14,05] | 93,35 | 176,03 / 2 642,57 | 1,55 | 0,024 | 31,7 |
| `tor_socks` | 5 | 1,91 [0,37; 2,45] | 362,84 | 1 098,35 / 5 114,89 | 419,93 | 0,005 | 31,7 |

Ratio pareado (mediana): **0,172** [0,051; 0,572]; ratios por trial: 0,572 / 0,051 / 0,172 / 0,289 / 0,160. Taxa de conclusão pareada (Tor/Surface): mediana **7,67×** [1,89; 21,81].

## 2. Leitura honesta

1. **Nesta máquina/enlace, o Tor entregou ~17–22% do goodput da Surface** para um GET de 256 KiB (medianas pareadas de duas execuções independentes). O TTFB foi 2,4–3,9× maior e o estabelecimento foi 241–271× mais caro (330–420 ms contra ~1,4–1,6 ms de TCP direto).
2. **A dispersão é grande e real.** Cada run teve trials em que a Surface parou por 2,5–3,2 s; no run 1, dois de cinco trials têm ratio >1 (Tor "mais rápido"). Isso não é erro de medição: é o comportamento do enlace de acesso e do servidor público. Consequência: qualquer número deste tier precisa do IC e da distribuição por trial, e nenhum valor pontual deve ser tratado como constante da rede.
3. **O que é consistente entre runs**: Tor tem goodput menor, TTFB maior e custo de estabelecimento ~2 ordens de grandeza maior que TCP direto. O que **não** é consistente é o valor exato do ratio (0,17 vs 0,22) nem o IC.
4. **Nenhuma extrapolação para o AEGIS.** Comparar o ratio lab do AEGIS (10–22%) com o ratio público do Tor (17–22%) seria comparar *tiers* diferentes e é proibido por `05` §1.

## 3. Por que o AEGIS não pode ser medido aqui

O protótipo rejeita qualquer host que não seja IPv4 loopback (`telescoping.py:144-150, 230-233, 2935-2937`; `onion_relay.py:148-149`). Não é decisão de configuração: `RelayDescriptor.__post_init__` valida o host e o CLI dos relays também. Portanto:

- não existe hoje um número de desempenho do AEGIS em caminho real;
- a meta de 90% **não pode ser declarada atingida ou não** em WAN até o transporte deixar de ser loopback-only;
- o caminho honesto para medir WAN é implantar o transporte (mudança de arquitetura — P1 em `03`), não simular e chamar de rede real.

## 4. O que este tier estabelece para a missão

1. **Denominador competitivo**: numa conexão de acesso real, o Tor entrega ~1/5 do goodput direto nesta carga. A meta de 90% da Surface é, portanto, ~4,5–5,3× mais exigente que o desempenho do Tor medido aqui — o que torna a conciliação entre desempenho e privacidade ainda mais difícil, e não mais fácil.
2. **Custo de estabelecimento do AEGIS não é o problema**: 25–30 ms (lab) contra 330–420 ms de estabelecimento Tor no público. Nesse quesito o protótipo já é melhor.
3. **O AEGIS tem folga de banda**: overhead de 1–3% em volume, contra a expectativa de que uma rede de anonimato pague caro em bytes.

## 5. Limitações declaradas

- HTTP/1.1 em claro (sem TLS) para que os dois braços paguem o mesmo protocolo de aplicação; o custo de TLS fica fora do número, igualmente para ambos.
- Um único alvo público, uma única hora por run, um único host, 5 trials por braço em cada run.
- O proxy contador fica em loopback à frente do SOCKS; ele não modela a rede.
- Tor foi medido através de um SOCKS local recém-iniciado, com `ClientOnly 1`; guards e caminhos variam por conexão e entre runs.
- Nenhuma conclusão sobre anonimato: este documento trata exclusivamente de desempenho.

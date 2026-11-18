# 05 — Plano de benchmark Surface × Tor × AEGIS

- **Pergunta**: quanto do desempenho da Surface o AEGIS entrega, e quanto do Tor ele entrega, quando origem, destino, payload, duração e condições de rede são equivalentes?
- **Meta**: `goodput(AEGIS) / goodput(Surface) ≥ 0.90` no tier correspondente, com IC de 95%; latência reportada lado a lado, nunca mascarada.
- **Implementação**: `src/anonlab/thor_lab/` (código desta entrega), artefatos brutos em `experiments/thor-lab/`.

## 1. Tiers (nunca misturados)

| Tier | O que é | O que valida | O que não valida |
|---|---|---|---|
| `lab` | Todos os endpoints em IPv4 loopback, mesmo host, mesmo processo Python, sem shaping | custo de implementação (CPU, cópias, framing, AEAD, dispatch) com origem/destino/payload idênticos | WAN, perda, fila, jitter, Tor, anonimato |
| `emulated` | Loopback + shaper de enlace em espaço de usuário no enlace de acesso (`DEFAULT_PROFILES`) | sensibilidade a RTT/taxa de um enlace de acesso | perda, retransmissão, fila de pacotes, path diversity |
| `public` | Endpoints públicos reais na Internet via enlace de acesso do host | linha de base real Surface × Tor nesta máquina/horário | AEGIS (não é implantável — ver `01` F7); generalização para outras redes |

**Regra dura**: um ratio só existe dentro de um tier. O relatório recusa-se a produzir um número único "AEGIS vs Tor" — e o `summarize` só avalia o gate com o braço `surface` do mesmo tier.

## 2. Braços

| Braço | Definição | O que isola |
|---|---|---|
| `surface` | TCP direto cliente→endpoint (loopback ou público) | linha de base "Surface" |
| `relay3_plain` | 3 relays TCP sem criptografia, mesma topologia de saltos, mesma semântica de eco (`backends.PlainChainBackend`) | custo de saltos/cópias/`asyncio` **sem** cripto |
| `aegis_telescope3` | o protótipo real: `RelayNode` ×3, handshake por hop, AEAD por hop, streams duplex multiplexadas (`telescoping.TelescopingClient`) | custo de anonimato do AEGIS |
| `tor_socks` | Tor real local (`tor.exe` 0.4.x expert bundle) via SOCKS5 (`socks5.open_socks5`) | linha de base Tor real (apenas tier public) |

Todos os braços passam por um **proxy contador** idêntico (`counting_proxy.CountingProxy`) imediatamente à frente do primeiro salto, para que bytes de fio sejam contados do mesmo ponto de observação (o enlace de acesso do cliente). O custo do proxy é pago igualmente por todos os braços; o `REPORT.md` do run registra que ele está presente.

## 3. Workloads

| Workload | Parâmetros | Mede |
|---|---|---|
| `bulk_echo:<bytes>` | payload, chunk de 16 KiB, até 4 comandos em voo | goodput, TTFB, overhead de banda, CPU/RSS |
| `small_rtt:<bytes>x<ops>` | 1 KiB × 50 operações sequenciais | latência por operação p50/p95/p99, custo por comando |
| `parallel_bulk:<bytes>x<streams>` | 8 streams × 64 KiB simultâneas | concorrência, contenção, tempo de estabelecimento por conexão |
| `http_get:<ops>` | HTTP/1.1 `GET` real contra endpoint público, com `Range: bytes=0-262143` | TTFB, goodput fim-a-fim, tempo de estabelecimento de circuito/SOCKS |

Payloads são pseudoaleatórios e determinísticos pela seed (`workloads.PayloadFactory`) — nunca tráfego real, nunca dado sensível.

## 4. Métricas (definições operacionais)

1. **Goodput** = bits de payload útil ÷ tempo de parede entre a primeira escrita e o último byte recebido. Uma direção de payload útil por round trip; documentado no relatório.
2. **TTFB** = tempo até o primeiro byte de resposta (para `http_get`, primeiro byte do corpo é reportado separadamente como `first_body_byte_ms`).
3. **Latência p50/p95/p99** = percentis por operação (round-trip workloads) e **completion p95/p99** = percentis por trial (bulk).
4. **Tempo de estabelecimento** = soma dos passos medidos por braço: `tcp_connect` (Surface), `socks_connect` (Tor, inclui construção de circuito Tor), `guard_connect`+`extend_*`+`stream_open` (AEGIS).
5. **CPU** = `process_time` do processo inteiro durante o trial ÷ tempo de parede (fração de um núcleo). **Inclui os relays in-process** do AEGIS e da cadeia — é o custo total do caminho, que é o que um operador paga; não é o custo do cliente isolado.
6. **Memória** = working set no início/fim e pico do processo (Windows `psapi`, Linux `/proc/self/status`).
7. **Overhead de banda** = bytes contados no proxy ÷ bytes de payload, separado por subida e descida.
8. **Estabilidade** = presença de erros/timeouts por braço (registrados, nunca descartados) e dispersão entre trials (desvio e IC).

## 5. Protocolo estatístico

1. **Interleaving**: braços são medidos em rodízio dentro de cada trial, com rotação da ordem a cada trial, para que deriva térmica/carga não caia só em um braço.
2. **Warmup**: 1 rodada de aquecimento por braço, **registrada** nos artefatos com `warmup: true` e excluída dos gates.
3. **n**: 7 trials no tier lab, 5 nos demais. IC bootstrap (2000 reamostragens, seed fixa) reportado como `[low, high]`; com n<5 o IC é marcado `reliable: false`.
4. **Gate**: só é avaliado com ≥3 trials pareados válidos; caso contrário `insufficient_data` com razão explícita. O ratio é a mediana dos ratios pareados por índice de trial.
5. **Nada é descartado**: erros, timeouts e warmups ficam no `trials.jsonl`; o summary conta cada categoria.
6. **Nada é reexecutado para "melhorar"**: um run é um diretório imutável; um novo run é um novo diretório com novo `run_id`.

## 6. Critérios de aceitação e regras de parada

- **Aceitação de desempenho (C3)**: mediana do ratio de goodput ≥ 0,90 com IC de 95% no tier; sem piora de integridade (todo eco conferido) e sem erro.
- **Aceitação de latência**: reportar p95/p99 por braço; não há gate numérico de latência na missão, então nenhum é inventado. A meta declarada é igualdade de desempenho, e goodput é o critério primário.
- **Parada**: uma campanha é interrompida se a taxa de erros de um braço exceder 20% dos trials (o artefato registra a interrupção e o motivo) ou se o resultado de um trial indicar falha de integridade (eco diferente) — nesse caso o run é marcado parcial e o relatório não apresenta ratio até investigação.
- **Proibição**: comparar loopback com Tor público, comparar workloads de tamanhos diferentes, ou usar o melhor trial. O gate usa todos os trials válidos.

## 7. Estrutura de artefatos e reprodução

```
experiments/thor-lab/<run-id>/
  manifest.json      # revisão git + dirty + ambiente + configuração + digest
  trials.jsonl       # 1 linha por trial (bruto, imutável)
  availability.json  # braços que não puderam rodar e por quê
  run.json           # id, alvo, contagem, escopo
  summary.json       # derivado: percentis, IC, gates, digest do bruto
  REPORT.md          # derivado do summary.json
```

Comandos:

```bash
python -m anonlab.thor_lab probe
python -m anonlab.thor_lab run --tier lab --out experiments/thor-lab/lab-01 \
    --arms surface,relay3_plain,aegis_telescope3 \
    --workloads bulk_echo:262144,bulk_echo:1048576,small_rtt:1024x50,parallel_bulk:65536x8 \
    --trials 7 --warmup 1
python -m anonlab.thor_lab summarize experiments/thor-lab/lab-01
python -m anonlab.thor_lab report experiments/thor-lab/lab-01
python -m anonlab.thor_lab verify experiments/thor-lab/lab-01   # recomputa SHA-256 do bruto e o digest de configuração
```

Tier público (exige um Tor local em `127.0.0.1:9050`; sem ele, `availability.json` registra `socks_port_unreachable`):

```bash
python -m anonlab.thor_lab run --tier public \
    --public-url http://cachefly.cachefly.net/1mb.test \
    --http-header "Range: bytes=0-262143" \
    --arms surface,tor_socks --workloads http_get:1 --trials 5 --warmup 1 \
    --out experiments/thor-lab/public-01
```

## 8. Ameaças à validade (declaradas)

1. **Host de 4 vCPUs, Windows 10**, com antivírus e outros processos: ruído entre trials; por isso interleaving, IC e n≥5.
2. **Loopback não é rede**: sem perda, sem RTT real, sem fila; o tier lab mede implementação, não Internet.
3. **O proxy contador adiciona um salto loopback** a todos os braços; por isso o `surface` do tier lab é o próprio `surface` através do proxy (tratamento igual), e o tier público tem o mesmo proxy dos dois lados.
4. **CPU inclui relays in-process**: comparação justa de custo total do caminho, injusta como "CPU do cliente".
5. **Tier público muda a cada hora**: rotas Tor, congestionamento do servidor público e do enlace local. O run registra hora, alvo e ambiente; generalização exige repetição em outros horários/hosts.
6. **Sem TLS no tier público**: HTTP/1.1 em claro, escolhido para que Surface e Tor paguem o mesmo protocolo de aplicação; o custo de TLS fica fora do número (e é igual para os dois braços).
7. **AEGIS não participa do tier público**: o transporte é loopback-only (F7). Nenhum número público de AEGIS é apresentado, e nenhuma extrapolação é feita.

## 9. O que este plano não faz

- Não avalia anonimato; isso é o protocolo de `04-THREAT-MODEL.md` §5.
- Não mede perda de pacotes, porque o shaper não modela perda (`network_impairment.py:1-7`). A avaliação de perda sob condições de rede reais exige Shadow/`tc-netem` em Linux (ver `02`, vereditos) e está registrada como trabalho não executado.
- Não mede múltiplos hosts nem WAN; a única forma honesta de fazer isso hoje seria tornar o transporte implantável — o que é uma mudança de arquitetura, não de medição.

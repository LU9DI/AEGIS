# THOR — programa de pesquisa em desempenho e privacidade do AEGIS

Esta pasta contém a primeira entrega do programa de pesquisa tecnológica, privacidade e desempenho do AEGIS/THOR. Ela foi produzida a partir do commit `d8b84d531a77318d578224c9ece9fd3bab184037`, na branch `research/thor-performance-privacy-lab`.

## As duas metas (inalteradas, não negociáveis)

1. **Privacidade e anonimato** iguais ou superiores aos do Tor, sob modelos de adversário comparáveis.
2. **Desempenho** de pelo menos 90% da Surface (conexão direta), buscando igualdade, sem sacrificar privacidade para obter velocidade.

Nenhum documento desta pasta reduz essas metas para acomodar a implementação atual. Quando o protótipo está longe delas, o texto diz o número e o motivo.

## Ordem de leitura

| Documento | Conteúdo |
|---|---|
| [`01-ARCHITECTURE-AUDIT.md`](01-ARCHITECTURE-AUDIT.md) | arquitetura de transporte/relays do código atual, custo por comando, achados F1–F12, dependências e lacunas de medição |
| [`02-TECHNOLOGY-MATRIX.md`](02-TECHNOLOGY-MATRIX.md) | matriz comparativa (Rust/Tokio/Quinn, s2n-quic, QUIC/HTTP3, MASQUE, OHTTP, HPKE, BLAKE3, CC/pacing, shaping/padding, Shadow/ns-3) com benefício, custo, maturidade, licença, riscos e veredito |
| [`03-BOTTLENECKS.md`](03-BOTTLENECKS.md) | gargalos priorizados com evidência medida e hipóteses falsificáveis |
| [`04-THREAT-MODEL.md`](04-THREAT-MODEL.md) | adversários A1–A8, ativos, suposições de confiança, protocolo de avaliação de privacidade e critérios de falsificação |
| [`05-BENCHMARK-PLAN.md`](05-BENCHMARK-PLAN.md) | tiers lab/emulado/público, braços, workloads, métricas, protocolo estatístico, critérios de aceitação e parada |
| [`06-LAB-RESULTS.md`](06-LAB-RESULTS.md) | resultados medidos em loopback: Surface × cadeia TCP sem cripto × AEGIS, com CPU, RSS, bytes de fio e IC |
| [`07-PUBLIC-RESULTS.md`](07-PUBLIC-RESULTS.md) | linha de base real Surface × Tor no mesmo host/alvo, e por que o AEGIS não tem número público |
| [`08-PROTOTYPE-RESULTS.md`](08-PROTOTYPE-RESULTS.md) | protótipo isolado do caminho quente, comparação antes/depois e decisão de integração com evidência |

## Código desta entrega

- `src/anonlab/thor_lab/` — harness de medição reproduzível: braços (`backends.py`), proxy contador (`counting_proxy.py`), SOCKS5 (`socks5.py`), protocolos de aplicação (`appproto.py`), workloads (`workloads.py`), runner imutável (`runner.py`), estatística (`stats.py`), derivados (`metrics.py`), relatório (`report.py`), proveniência (`provenance.py`), recursos (`resources.py`), resolução de timer (`timers.py`), microbenchmark de caminho quente (`fast_path.py`).
- `tests/test_thor_lab_*.py` — 33 testes (inclui SOCKS5 contra servidor falso, HTTP com `Content-Length` e chunked, braço AEGIS de 3 hops, digest/verificação, gates e gramática de workload).
- `experiments/thor-lab/<run-id>/` — artefatos brutos e derivados de cada campanha (ver `05-BENCHMARK-PLAN.md` §7).

## Como reproduzir

```bash
python -m pytest tests/test_thor_lab_*.py
python -m anonlab.thor_lab probe
python -m anonlab.thor_lab run --tier lab --out /tmp/lab \
    --arms surface,relay3_plain,aegis_telescope3 \
    --workloads 'bulk_echo:262144,bulk_echo:262144@65536i4,small_rtt:1024x50' \
    --trials 7 --warmup 1
python -m anonlab.thor_lab summarize /tmp/lab
python -m anonlab.thor_lab report /tmp/lab
python -m anonlab.thor_lab verify /tmp/lab
python -m anonlab.thor_lab.fast_path --output /tmp/fastpath.json
```

## Disciplina de alegação (vale para todo o programa)

- Nenhum número desta pasta prova anonimato. Anonimato exige o protocolo de avaliação de `04-THREAT-MODEL.md` §5, que ainda não foi executado.
- Ratios só existem **dentro** de um tier. Loopback nunca é comparado com Tor público.
- Todo número é rastreável ao commit, ao manifesto, ao seed e ao digest do arquivo bruto; `verify` recomputa o SHA-256.
- Resultado desfavorável é resultado. Warmups, erros e timeouts ficam registrados.
- O que não foi medido está declarado como não medido — inclusive perda de pacotes, WAN, múltiplos hosts e qualquer defesa de *website fingerprinting*.

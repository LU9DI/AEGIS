# THOR P2 lab — crédito de leitura, evento de resposta e ACK

Laboratório isolado do P2 (base P1 `baecf8375704ad58d544712a410de725b1689360`). Nenhuma
variante altera o caminho padrão: todos os knobs em `src/anonlab/telescoping.py` têm
default igual à constante de produção, e `tests/test_thor_p2_lab.py` pina isso.

## Estrutura

| Caminho | Conteúdo |
|---|---|
| `src/anonlab/thor_p2_lab/variants.py` | registro de braços, uma dimensão por braço, validação |
| `src/anonlab/thor_p2_lab/runner.py` | workloads P0/P1, trial real de 3 hops, métricas |
| `src/anonlab/thor_p2_lab/campaign.py` | campanha pareada intercalada, bootstrap, critério de decisão |
| `src/anonlab/thor_p2_lab/__main__.py` | CLI `run` / `trial`, manifesto com SHA-256 |
| `analyze_campaign.py` | renderiza `summary.json` em tabelas Markdown |
| `soak.py` | soak curto: alterna dois braços por N segundos, mede deriva e RSS |
| `campaign-01/` | 315 trials brutos, `summary.json`, `manifest.json`, `TABLES.md` |
| `soak-01/soak.json` | 120 s, 166 trials intercalados |

## Comandos

```bash
python -m anonlab.thor_p2_lab trial --variant control --workload bulk_256k_c16k --trials 3
python -m anonlab.thor_p2_lab run --output experiments/thor-p2-lab/campaign-01
python experiments/thor-p2-lab/analyze_campaign.py experiments/thor-p2-lab/campaign-01
python experiments/thor-p2-lab/soak.py --seconds 120 --output experiments/thor-p2-lab/soak-01
```

## Registro de variantes (campanha-01, commit `8c35be6`)

| Braço | Dimensão | Decisão |
|---|---|---|
| `control` | — | referência |
| `credit-window-128k` | janela inicial 128 KiB | rejeitada |
| `credit-window-256k` | janela inicial 256 KiB | rejeitada |
| `credit-policy-32k-1ms` | lote 32 KiB / prazo 1 ms | rejeitada |
| `credit-policy-128k-4ms` | lote 128 KiB / prazo 4 ms | rejeitada |
| `credit-policy-window-aware` | prazo só dispara com crédito pendente ≥ 32 KiB | rejeitada pelo critério (3/5 ganhos, 1 p95 mediano acima) |
| `events-32k` | leitura do exit 32 KiB | rejeitada |
| `events-64k` | leitura do exit 64 KiB | rejeitada (corta eventos/AEAD, goodput não reprodutível em 2 workloads) |
| `ack-pipeline` | ACK de crédito fora do caminho de leitura | rejeitada (regressão medida) |

Relatórios: `docs/research/thor/12-RELAY-CREDIT-EVENT-AUDIT.md` (Fase 1),
`13-RELAY-CREDIT-EVENT-SECURITY-REVIEW.md` (Fase 3),
`14-RELAY-CREDIT-EVENT-RESULTS.md` (Fases 2 e 4).

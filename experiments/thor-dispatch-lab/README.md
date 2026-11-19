# experiments/thor-dispatch-lab — artefatos do experimento P1 (batching e despacho)

Cada subdiretório é **um run imutável** do harness (`anonlab.thor_lab.run`) ou um **relatório JSON** do perfilador (`anonlab.thor_lab.dispatch_profile`). Todos foram produzidos com a árvore limpa no commit **`bbb0e3f4affbe305cd10053e3b980021f5233c1d`** (`dirty: false` nos manifestos), 0 erros e 0 falhas de integridade.

| Diretório/arquivo | O que é | Registros | SHA-256 do bruto (`trials.jsonl`) | Documento |
|---|---|---|---|---|
| `campaign-01/` | 6 braços × 4 workloads × 7 trials + 1 warmup, ordem intercalada | 192 | `c9f3c3e1177b397eea0d89c6b347116ab462d32512094900cacda99a8037deb8` | `docs/research/thor/10` §2 |
| `ab-io-batch-01/` | A/B pareado controlo vs `io_batch`, 20 trials + 2 warmup | 88 | `b72186c0b907920824facc32a50fe5462c27dcf293f0298ec145aa26a67aae58` | `docs/research/thor/10` §3 |
| `profile-01.json` | perfil de custo de despacho, 4 variantes × 2 execuções × 48 comandos | — | arquivo: `a012c837a8f9f335a3097697c9237cae953df775fa3e2b46b8b2f5b968b2ca9a` | `docs/research/thor/09` |
| `soak-01.json` | carga duplex concorrente, 4 streams × 128 comandos, controlo vs `combined` | — | arquivo: `80a8efe1ad66a24841b0262cd93293325389cab30aad27f06bcdb195581417e4` | `docs/research/thor/10` §5 |

Braços da campanha: `surface`, `relay3_plain`, `aegis_telescope3` (controlo), `aegis_io_batch`, `aegis_lean_dispatch`, `aegis_combined`.

## Comandos que produziram os artefatos

```bash
# profile-01.json (Fase 1)
python -m anonlab.thor_lab.dispatch_profile --variants control,io_batch,lean_dispatch,combined \
  --chunk-bytes 65536 --commands 48 --batch-size 4 --repeats 2 \
  --output experiments/thor-dispatch-lab/profile-01.json

# campaign-01 (Fase 4)
python -m anonlab.thor_lab run --tier lab --out experiments/thor-dispatch-lab/campaign-01 \
  --arms surface,relay3_plain,aegis_telescope3,aegis_io_batch,aegis_lean_dispatch,aegis_combined \
  --workloads 'bulk_echo:1048576,bulk_echo:262144,bulk_echo:262144@262144i4,parallel_bulk:65536x8' \
  --trials 7 --warmup 1 --seed 20261118 \
  --notes "P1 dispatch batching; control vs io_batch vs lean_dispatch vs combined; interleaved"

# ab-io-batch-01 (20 trials pareados)
python -m anonlab.thor_lab run --tier lab --out experiments/thor-dispatch-lab/ab-io-batch-01 \
  --arms aegis_telescope3,aegis_io_batch \
  --workloads 'bulk_echo:1048576,bulk_echo:262144' \
  --trials 20 --warmup 2 --seed 20261119 --notes "focused paired A/B control vs io_batch"

# soak-01.json (carga duplex concorrente)
python -m anonlab.thor_lab.dispatch_profile --variants control,combined \
  --chunk-bytes 65536 --commands 128 --batch-size 4 --streams 4 --repeats 1 \
  --output experiments/thor-dispatch-lab/soak-01.json
```

## Estrutura de cada run

`manifest.json` (revisão, dirty, ambiente, configuração, digest canônico), `trials.jsonl` (bruto), `availability.json`, `run.json`, `summary.json` e `REPORT.md` (derivados). Regenerar e verificar:

```bash
python -m anonlab.thor_lab summarize experiments/thor-dispatch-lab/campaign-01
python -m anonlab.thor_lab report experiments/thor-dispatch-lab/campaign-01
python -m anonlab.thor_lab verify experiments/thor-dispatch-lab/campaign-01
```

## Regras

- Não editar `trials.jsonl` nem `manifest.json`. Um novo experimento é um novo diretório.
- Os artefatos de uma execução exploratória anterior (árvore suja) foram **preservados fora do repositório** e não são citados em nenhum documento; apenas os quatro acima são evidência.
- Nenhum arquivo contém payload real, chave ou endereço sensível: os payloads são pseudoaleatórios determinísticos pela seed.

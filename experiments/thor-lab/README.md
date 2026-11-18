# experiments/thor-lab — artefatos de medição do programa THOR

Cada subdiretório é **um run imutável** produzido por `python -m anonlab.thor_lab run`. `trials.jsonl` é bruto; `summary.json` e `REPORT.md` são derivados e podem ser regenerados; `verify` recomputa o SHA-256 do bruto e o digest da configuração.

Todos os runs abaixo foram produzidos com o harness no commit **`1aa9130539a30c7ab7c62f116b4fa8771709c584`**, com árvore limpa (`dirty: false` no `manifest.json` de cada run).

| Diretório | Tier | Seed | Registros | Erros | SHA-256 de `trials.jsonl` | Documento |
|---|---|---|---|---|---|---|
| `lab-01/` | lab | 20261118 | 144 | 0 | `88220ea1f296d89e276b5e110e5d4cbe4a58adeac3212c1af30910b9d11246b6` | `docs/research/thor/06-LAB-RESULTS.md` |
| `emulated-01/` | emulated (metro) | 20261118 | 54 | 0 | `d8d567c30265c10bd47cbc7399116cd6627880ad74556bdbe69197a3c19677d9` | `docs/research/thor/06-LAB-RESULTS.md` §6 |
| `public-01/` | public | 20261118 | 12 | 0 | `ced15accc8fa926ededcdae7d765e11b9cbf5a24238c0d3b0c2a0d2d7c838b11` | `docs/research/thor/07-PUBLIC-RESULTS.md` |
| `public-02/` | public | 20261119 | 12 | 0 | `46f6a6fcb2b1aa7a217d4dcf38591d2bc7aa3faeba23950fa41a53b79490c6a4` | `docs/research/thor/07-PUBLIC-RESULTS.md` |
| `fastpath-01.json` | microbenchmark | — | 3 000 repetições/operação | — | — | `docs/research/thor/08-PROTOTYPE-RESULTS.md` |

## Comandos que produziram cada artefato

```bash
# lab-01
python -m anonlab.thor_lab run --tier lab --out experiments/thor-lab/lab-01 \
  --arms surface,relay3_plain,aegis_telescope3 \
  --workloads 'bulk_echo:262144,bulk_echo:262144@65536i4,bulk_echo:262144@262144i4,bulk_echo:1048576,small_rtt:1024x50,parallel_bulk:65536x8' \
  --trials 7 --warmup 1 --seed 20261118 \
  --notes "tier lab; chunk-size sweep; 1ms timer resolution; harness at commit 1aa9130"

# emulated-01
python -m anonlab.thor_lab run --tier emulated --profile metro --out experiments/thor-lab/emulated-01 \
  --arms surface,relay3_plain,aegis_telescope3 \
  --workloads 'bulk_echo:262144,bulk_echo:262144@65536i4,small_rtt:1024x20' \
  --trials 5 --warmup 1 --seed 20261118 \
  --notes "tier emulated, metro shaper, harness at commit 1aa9130"

# public-01 / public-02 (Tor real em 127.0.0.1:9050)
python -m anonlab.thor_lab run --tier public \
  --public-url 'http://cachefly.cachefly.net/1mb.test' --http-header 'Range: bytes=0-262143' \
  --out experiments/thor-lab/public-01 \
  --arms surface,tor_socks --workloads 'http_get:1' --trials 5 --warmup 1 --seed 20261118 --timeout 120
# idem para public-02 com --seed 20261119

# fastpath-01.json
python -m anonlab.thor_lab.fast_path --repeats 3000 --output experiments/thor-lab/fastpath-01.json
```

## Ambiente

Windows 10.0.19045, Python 3.14.6 (CPython), 4 vCPUs, `cryptography 50.0.2`, resolução de timer elevada para 1 ms durante os runs (registrada em `manifest.json → extra.timer_resolution`). Tor: expert bundle oficial `tor-expert-bundle-windows-x86_64-16.0.1.tar.gz` (`9eed3c3ff1fe43df034ce360196c9ec95472560d77ff55614d0cd5120edea27b`), `tor.exe` `da22856f95ee24f8ace4ad1ab04acbd818fd6c3042bc3cf8f1d7cc3fa3edcb2b`, `SocksPort 127.0.0.1:9050`, bootstrap 100%.

## Estrutura de um run

| Arquivo | Papel |
|---|---|
| `manifest.json` | revisão git, dirty, ambiente, configuração completa e digest canônico |
| `trials.jsonl` | uma linha por trial (inclui warmup e erros) — **imutável** |
| `availability.json` | braços que não puderam rodar, com motivo legível por máquina |
| `run.json` | id, alvo, contagem, escopo de alegação |
| `summary.json` | derivado: percentis, IC bootstrap, ratios pareados, gates, digest do bruto |
| `REPORT.md` | derivado do `summary.json`, gerado por `python -m anonlab.thor_lab report` |

## Regras

- Não editar `trials.jsonl` nem `manifest.json`. Um novo experimento é um novo diretório.
- Regerar derivados: `python -m anonlab.thor_lab summarize <dir>` e `report <dir>`.
- Conferir integridade: `python -m anonlab.thor_lab verify <dir>` (deve retornar `ok: true`; falha se o bruto ou a configuração mudarem).
- Nenhum arquivo contém payload real de terceiros, identidade, chave ou endereço sensível: os payloads são pseudoaleatórios e determinísticos pela seed, e os trials registram apenas contadores, tempos e metadados de configuração.
- `logs/` guarda as saídas literais dos comandos de teste e de verificação.

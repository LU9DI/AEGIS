# EVIDENCE — comandos, códigos de saída e rastreabilidade

Este arquivo registra o que foi executado para produzir a entrega, com código de saída e resultado observado. Ele é deliberadamente redundante com os `manifest.json` de cada run: um leitor deve poder auditar a entrega sem confiar na narrativa.

- **Branch**: `research/thor-performance-privacy-lab`
- **Base obrigatória**: `d8b84d531a77318d578224c9ece9fd3bab184037`
- **Sem force push, sem reescrita de histórico, sem merge do PR #34, sem deploy.**

## 1. Commits desta entrega

| # | SHA completo | Assunto | Escopo |
|---|---|---|---|
| A | `13c45c3dbc204fa6f49ddff7569010febc570e57` | `research(thor): audit the transport data path and record the technology matrix` | documental: `01`, `02`, `04`, `05` (4 arquivos, 387 linhas) |
| B | `1aa9130539a30c7ab7c62f116b4fa8771709c584` | `perf(thor): add a reproducible Surface/Tor/AEGIS benchmark harness` | código: `src/anonlab/thor_lab/` (16 módulos), 4 arquivos de teste, `pyproject.toml` (21 arquivos, 4 600 linhas) |
| C | `316e1226d14ba0347aabc5757c498e49787c5576` | `docs(thor): record lab, emulated and public measurements with raw artifacts` | evidência: `docs/research/thor/03,06,07,08,README` + `experiments/thor-lab/` (37 arquivos, 9 657 linhas) |
| D | `03d2bbc5978d9b9a412cf53d31c6465dd8b57af9` | `docs(thor): log the commands, exit codes and revision chain` | este arquivo + correção de três fatores de headroom em `06` |
| E | `aa180ca27f03df3816271056096c4b950bb6e4f5` | `docs(thor): correct two cross-references in the research documents` | 2 linhas: faixa 14–34× em `08`, referência em `01` |
| F | `ace1e2764f5b69a94724c2adf89aacd51a147d41` | `docs(thor): record the last two commit SHAs` | esta tabela |
| G | SHA em `git log -1 -- tests/test_thor_lab_backends.py` | `test(thor): make the three-hop AEGIS arm test tolerant of host stalls` | timeout explícito + §7 deste arquivo (ver §7) |

A cadeia é linear, sem merge e sem reescrita: `d8b84d5 → 13c45c3 → 1aa9130 → 316e122 → 03d2bbc → aa180ca → ace1e27 → c692f23` (commits F e G). O diff total contra a base é de **63 arquivos, sem nenhuma remoção**; o número exato de inserções muda a cada commit que só toca este arquivo, então a fonte autoritativa é sempre `git diff --shortstat d8b84d531a77318d578224c9ece9fd3bab184037..HEAD` (14 784 inserções no commit G, HEAD `c692f23ad9938edf54ddb3788be7ad5e48e31c21`).

Arquivos alterados por commit: `git show --stat <sha>` (saída reproduzível em qualquer clone). Nenhum artefato histórico foi apagado ou sobrescrito; os arquivos desta entrega são todos novos, exceto `pyproject.toml`, que apenas ganhou dois entry points.

## 2. Comandos executados (com código de saída)

Todos os comandos de medição foram executados a partir de `C:\Users\lucas\AEGIS` com `PYTHONPATH=src`, `PYTHONDONTWRITEBYTECODE=1`, no commit B com árvore limpa.

| # | Comando | Saída | Código | Resultado |
|---|---|---|---|---|
| 1 | `git checkout -b research/thor-performance-privacy-lab` | branch criada a partir de `d8b84d5` | 0 | base correta |
| 2 | `python -m anonlab.thor_lab probe --socks 127.0.0.1:9050` | JSON com revision `1aa9130…`, `crypto_extra.available=true`, `tor_socks.available=true` | 0 | ambiente e Tor OK |
| 3 | `python -m pytest tests/test_thor_lab_stats.py tests/test_thor_lab_provenance.py tests/test_thor_lab_backends.py tests/test_thor_lab_runner.py` | `33 passed` (ver §7: houve uma falha transitória sob carga antes do endurecimento do timeout) | 0 | testes do harness |
| 4 | `python -m pytest tests/` (suíte completa) | `321 passed, 11 skipped, 1 failed in 637.77s` | 1 | falha pré-existente: `test_onion_protocol.py::test_three_hop_persistent_circuit_checks_monotonic_sequence`, teardown do Windows (`relay-3.log` aberto por subprocesso); não envolve o código desta entrega |
| 5 | `python -m anonlab.thor_lab run --tier lab … --out experiments/thor-lab/lab-01` | 144 registros, 3 braços, `partial: false` | 0 | ver `lab-01/` |
| 6 | `python -m anonlab.thor_lab run --tier emulated --profile metro …` | 54 registros, `partial: false` | 0 | ver `emulated-01/` |
| 7 | `python -m anonlab.thor_lab run --tier public … --seed 20261118` | 12 registros, Surface + Tor real | 0 | ver `public-01/` |
| 8 | `python -m anonlab.thor_lab run --tier public … --seed 20261119` | 12 registros, repetição independente | 0 | ver `public-02/` |
| 9 | `python -m anonlab.thor_lab.fast_path --repeats 3000 --output experiments/thor-lab/fastpath-01.json` | microbenchmark de 14 operações × 3 tamanhos | 0 | ver `fastpath-01.json` e `logs/fastpath.log` |
| 10 | `python -m anonlab.thor_lab verify experiments/thor-lab/<run>` (×4) | `ok: true` | 0 | bruto e configuração conferem (`logs/verify-*.log`) |

Ferramentas externas: Tor expert bundle oficial 16.0.1 (SHA-256 do arquivo e do `tor.exe` em `experiments/thor-lab/README.md`), bootstrap 100% verificado no log. Nenhum binário de terceiro foi versionado.

## 3. Artefatos e digests

| Diretório | Registros | Erros | `integrity_failures` | SHA-256 de `trials.jsonl` |
|---|---|---|---|---|
| `lab-01/` | 144 | 0 | 0 | `88220ea1f296d89e276b5e110e5d4cbe4a58adeac3212c1af30910b9d11246b6` |
| `emulated-01/` | 54 | 0 | 0 | `d8d567c30265c10bd47cbc7399116cd6627880ad74556bdbe69197a3c19677d9` |
| `public-01/` | 12 | 0 | 0 | `ced15accc8fa926ededcdae7d765e11b9cbf5a24238c0d3b0c2a0d2d7c838b11` |
| `public-02/` | 12 | 0 | 0 | `46f6a6fcb2b1aa7a217d4dcf38591d2bc7aa3faeba23950fa41a53b79490c6a4` |

Cada `manifest.json` registra `code.revision = 1aa9130539a30c7ab7c62f116b4fa8771709c584` e `code.dirty = false`, além de ambiente, configuração completa, digest canônico da configuração e a elevação de resolução de timer aplicada (`extra.timer_resolution`).

## 4. Resultado numérico em uma linha (com o IC, não sem ele)

- **Lab, 1 MiB**: AEGIS = 0,0997 [0,0876; 0,1120] da Surface. **Meta de 90% não atingida** (headroom 9,03×).
- **Lab, 256 KiB**: AEGIS = 0,1474–0,1729 da Surface, conforme o tamanho de comando (headroom 5,2–6,1×).
- **Emulado (metro)**: AEGIS = 0,1589 [0,1324; 0,2178] no volume de 16 KiB e 0,7603 [0,6963; 0,8719] em round-trip de 1 KiB.
- **Público**: Tor = 0,172–0,217 da Surface em goodput, com IC largo (0,051–1,858) e TTFB 2,4–3,9× maior; estabelecimento 241–271× mais caro. O AEGIS não é medível neste tier (transporte loopback-only).
- **Microbenchmark**: teto de cripto+cópias em cadeia de 3 hops = 524 Mb/s (comando 16 KiB) e 640 Mb/s (256 KiB), contra 21,9–37,8 Mb/s medidos → o gargalo é despacho, não criptografia.

## 5. O que não foi executado, e por quê

| Item | Motivo | Consequência |
|---|---|---|
| Protótipo Rust/tokio | `rustc` e `cargo` ausentes na máquina (verificado com `Get-Command`) | nenhuma alegação sobre ganho de Rust; desenho e critérios em `08` §5 |
| Shadow / ns-3 | exigem Linux; sem esses ambientes aqui | nenhuma alegação de simulação de rede |
| Perda de pacotes / estabilidade sob perda | o shaper do repositório não modela perda (`network_impairment.py:1-7`) | declarado como não medido em `05` §9 |
| Múltiplos hosts / WAN real para o AEGIS | transporte loopback-only (`01` F7) | meta de 90% não é avaliável em WAN hoje |
| Avaliação forte de website fingerprinting | sem corpus de traces reais no repositório | protocolo definido em `04` §5; nenhuma alegação de paridade com o Tor |

## 6. Reprodução

```bash
python -m pytest tests/test_thor_lab_*.py
python -m anonlab.thor_lab verify experiments/thor-lab/lab-01
python -m anonlab.thor_lab summarize experiments/thor-lab/lab-01
python -m anonlab.thor_lab report experiments/thor-lab/lab-01
```

Em ambientes onde o diretório temporário do sistema não permite subdiretórios (sandbox), defina `THOR_LAB_TEST_TMP` para um diretório gravável antes de rodar o pytest — foi o único ajuste de ambiente necessário, e ele não altera nenhum teste.

## 7. Validação pós-publicação (divergência de publicação resolvida)

A primeira validação independente encontrou a divergência abaixo. Ela era real e a causa era simples: **os commits existiam apenas no clone local; nunca houve push.**

### 7.1 Diagnóstico

| Verificação | Resultado |
|---|---|
| `git remote -v` | `origin https://github.com/LU9DI/AEGIS.git` (fetch e push) |
| `git branch --show-current` | `research/thor-performance-privacy-lab` |
| `git rev-parse HEAD` | `ace1e2764f5b69a94724c2adf89aacd51a147d41` |
| `git cat-file -t` nos seis SHAs | `commit` em todos (13c45c3, 1aa9130, 316e122, 03d2bbc, aa180ca, ace1e27) |
| `git ls-remote --heads origin refs/heads/research/thor-performance-privacy-lab` (antes) | `d8b84d531a77318d578224c9ece9fd3bab184037` — isto é, a branch remota existia apontando para a **base**, sem os seis commits |
| `git rev-list --left-right --count origin/<branch>...HEAD` (antes) | `0 6` — zero atrás, seis à frente |
| `git merge-base --is-ancestor origin/<branch> HEAD` | exit `0` → fast-forward, sem force |

### 7.2 Publicação

```
git push origin research/thor-performance-privacy-lab
push_exit=0
To https://github.com/LU9DI/AEGIS.git
   d8b84d5..ace1e27  research/thor-performance-privacy-lab -> research/thor-performance-privacy-lab
```

Depois do push, `git ls-remote --heads origin` retornou `ace1e2764f5b69a94724c2adf89aacd51a147d41`, e `git merge-base --is-ancestor <sha> origin/research/thor-performance-privacy-lab` retornou `0` para **cada um dos seis commits**. Nenhum force push, nenhum merge, nenhuma reescrita, e `refs/pull/34/head` permaneceu em `d8b84d531a77318d578224c9ece9fd3bab184037` — o PR #34 não foi tocado.

### 7.3 Falha transitória encontrada na validação pós-push

A primeira execução dos testes após o push terminou com **`1 failed, 32 passed` (exit 1)**: `tests/test_thor_lab_backends.py::test_aegis_arm_round_trips_through_three_aead_hops` estourou `TimeoutError` com um teto de 30 s. A investigação mostrou que não era defeito de protocolo:

- o teste isolado passou em **3,91 s** (exit 0);
- o arquivo inteiro passou **11/11 em 4,37 s**, com o caso AEGIS em **0,39 s**;
- a execução combinada que falhou levou **72 s** contra **27 s** de uma execução anterior — máquina compartilhada com o daemon Tor, antivírus e outros processos.

Conclusão: o teto de 30 s era apertado demais para um host compartilhado, e a falha era um stall de SO, não um deadlock. Correção (commit G): constante explícita `_AEGIS_TEST_TIMEOUT_S = 120.0` usada no `connect` e na leitura, com comentário que explica a razão e mantém o teste capaz de falhar em caso de hang real. O teto coincide com o teto por trial do runner de medição.

### 7.4 Re-execuções registradas

| Execução | Comando | Resultado | Código |
|---|---|---|---|
| 1 | os quatro arquivos `tests/test_thor_lab_*.py` | `33 passed in 20.72s` | 0 |
| 2 | idem | `33 passed in 15.15s` | 0 |
| 3 (log publicado) | idem, `-v`, saída gravada em `experiments/thor-lab/logs/pytest-thor-lab.log` | `33 passed in 24.85s` | 0 |
| — | `python -m anonlab.thor_lab verify experiments/thor-lab/lab-01` | `"ok": true`, `records: 144` | 0 |

Nenhum artefato de medição foi alterado por esta correção: os quatro runs, o `fastpath-01.json` e seus digests permanecem exatamente como no commit C.


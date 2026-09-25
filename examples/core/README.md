# Exemplos da área `core` (DD-00)

Cada exemplo abaixo demonstra uma feature opcional do núcleo (§3.2 "Regra
transversal: exemplos de features opcionais"). `tests/contract/test_examples.py`
(trilha H) valida todo `examples/**/*.yaml` com `dataipsum.validate`.

| Arquivo | Demonstra | Comando | Saída esperada |
|---|---|---|---|
| [`seed-fixa.yaml`](seed-fixa.yaml) | `seed` explícita: execuções repetidas produzem os mesmos bytes | `dataipsum generate --schema examples/core/seed-fixa.yaml --out <dir>` (duas vezes, diretórios diferentes) | os dois diretórios de saída são idênticos byte a byte |
| [`sem-seed.yaml`](sem-seed.yaml) | Seed ausente: sorteada e registrada no manifesto | `dataipsum generate --schema examples/core/sem-seed.yaml --out <dir>` | `<dir>/_manifest.json` contém `"seed_source": "random"` e um `seed` entre 0 e 2⁶³-1 |
| [`limites.yaml`](limites.yaml) | `chunk_size` e `limits.max_rows_total` customizados | `dataipsum generate --schema examples/core/limites.yaml --out <dir>` | dados gerados em chunks de 500 linhas; excedendo `max_rows_total` o comando falha com `ResourceLimitError` antes de gerar qualquer dado |
| [`plugin/`](plugin/) | Pacote externo mínimo (gerador `exemplo_placa`) registrado via entry point, e a allowlist `DATAIPSUM_PLUGINS` | ver [`plugin/README.md`](plugin/README.md) | sem a variável, o plugin não carrega (aviso logado); com `DATAIPSUM_PLUGINS=dataipsum-plugin-exemplo` ou `*`, carrega |
| [`docker/basico.sh`](docker/basico.sh) | Build da imagem base (sem extras) + `docker run` | `bash examples/core/docker/basico.sh` | imagem construída, roda como UID 10001 |
| [`docker/extras.sh`](docker/extras.sh) | `--build-arg EXTRAS=...` e a mesma imagem como worker Ray | `bash examples/core/docker/extras.sh` | imagem com os extras pedidos instalados, sem compilador |
| [`docker/fragmento.md`](docker/fragmento.md) | Como uma trilha adiciona seu próprio fragmento à imagem | — (guia, não executável) | — |

O comando `generate` é implementado pela trilha D (DD-01) e a CLI completa
pela trilha G (DD-02); até lá, os exemplos acima documentam o schema e o
comando esperado, e podem ser inspecionados hoje com:

```bash
uv run python -c "
from pathlib import Path
from dataipsum import load_schema, validate
schema = load_schema(Path('examples/core/seed-fixa.yaml'))
print(validate(schema))
"
```

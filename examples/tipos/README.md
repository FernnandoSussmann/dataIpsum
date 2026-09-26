# Exemplos da trilha A — Tipos primitivos e campos com regra (DD-01)

Cada exemplo abaixo demonstra uma feature opcional dos geradores da trilha A
(§3.2 "Regra transversal: exemplos de features opcionais" do DD-00). O comando
`dataipsum gen`/`generate` é implementado pela trilha D (execução); até lá,
valide a estrutura e a semântica de cada schema com o snippet no fim deste
arquivo.

| Arquivo | Demonstra | Comando | Saída esperada |
|---|---|---|---|
| [`todos-os-tipos.yaml`](todos-os-tipos.yaml) | Uma coluna de cada primitivo (`string`, `char`, `int`, `float`, `decimal`, `boolean`, `date`, `time`, `timestamp`, `uuid`, `json`, `array`), com parâmetros não padrão | `dataipsum gen --schema examples/tipos/todos-os-tipos.yaml --out <dir>` | 1000 linhas na tabela `amostras`, uma coluna por tipo |
| [`nulos.yaml`](nulos.yaml) | `null_ratio` em vários tipos | `dataipsum gen --schema examples/tipos/nulos.yaml --out <dir>` | colunas com a fração de nulos declarada; nenhuma coluna de PK tem nulo |
| [`documentos-invalidos.yaml`](documentos-invalidos.yaml) | `invalid_ratio` em `cpf`, `rg` e `cartao_credito`, para testar pipelines de validação a jusante | `dataipsum gen --schema examples/tipos/documentos-invalidos.yaml --out <dir>` | ~10% dos valores de cada coluna falham na validação correspondente (`is_valid_cpf`, `is_valid_rg_sp`, `luhn_is_valid`) |
| [`email-enderecos.yaml`](email-enderecos.yaml) | `email` com `name_column`, `unique: true`, `domains` customizados e `invalid_ratio` | `dataipsum gen --schema examples/tipos/email-enderecos.yaml --out <dir>` | a parte local de `email` deriva do nome da mesma linha (`nome`); endereços válidos são distintos entre si |
| [`formatacao.yaml`](formatacao.yaml) | `format: masked` × `unmasked` no mesmo dado | `dataipsum gen --schema examples/tipos/formatacao.yaml --out <dir>` | `cpf_masked` em `000.000.000-00`, `cpf_unmasked` em `00000000000` (e o mesmo para `rg`/`cartao_credito`) |
| [`cartoes-bandeiras.yaml`](cartoes-bandeiras.yaml) | `brands`, `weights` (ponderação por bandeira) e `extra_bins` (bandeira própria via BIN extra) | `dataipsum gen --schema examples/tipos/cartoes-bandeiras.yaml --out <dir>` | `cartao_principal` predominantemente Visa (~85%); `cartao_private_label` sempre com prefixo `987654` |
| [`locale-por-coluna.yaml`](locale-por-coluna.yaml) | Locale declarado no schema, na tabela e na coluna (precedência coluna > tabela > schema) | `dataipsum gen --schema examples/tipos/locale-por-coluna.yaml --out <dir>` | `nome`/`cpf` usam o locale `pt_BR` herdado da tabela |

## Aviso de segurança (DD-01 A.5, guardrail 7)

Os CPFs e números de cartão gerados aqui são **matematicamente válidos**
(dígito verificador correto), embora sintéticos. **Nunca** os use fora de
ambientes de teste: não os envie a serviços reais de validação de documento,
não os apresente como dados de clientes reais, e não os publique como se
fossem reais. Dados sintéticos nunca coincidem de propósito com dados reais,
mas a validade matemática por si só não os torna seguros para uso fora de
testes.

## Validando os exemplos hoje

Enquanto a trilha D (execução) e a trilha G (CLI) não existem, valide a
estrutura e a semântica (camadas 3 e 4 de "Validação em camadas", DD-00 §3.3)
com o registry da trilha A:

```bash
uv run python -c "
from pathlib import Path
from dataipsum.registry import Registry
from dataipsum.schema.loader import load_schema, validate
from dataipsum.schema.models import ValidationContext
from dataipsum.types import register as register_types

registry = Registry()
register_types(registry)
generators = {name: registry.get_generator(name)() for name in registry.generators}
ctx = ValidationContext(generators=generators)

for path in sorted(Path('examples/tipos').glob('*.yaml')):
    schema = load_schema(path)
    report = validate(schema, ctx)
    print(path.name, '->', 'OK' if report.is_valid else report.errors)
"
```

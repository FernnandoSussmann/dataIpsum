# Exemplos da área `relacoes` (DD-01, trilha B)

Cada arquivo abaixo demonstra uma feature opcional da trilha B (relações,
chaves e determinismo). Todos carregam com `dataipsum.load_schema` e
planejam com `dataipsum.relations.RelationsPlanner` sem depender de nenhuma
outra trilha (`tests/relations/unit/test_examples.py` valida isso). A CLI
completa (`dataipsum gen`/`dataipsum resume`) é da trilha G (DD-02) e não
está nesta branch; até o merge das duas, os comandos abaixo usam a API
Python diretamente.

| Arquivo | Demonstra | Saída esperada |
|---|---|---|
| [`um-para-muitos.yaml`](um-para-muitos.yaml) | `one_to_many` com `range` (`pedidos_faixa`) e `zipf` (`pedidos_zipf`, cauda longa) | `pedidos_faixa` tem entre 200 e 1000 linhas (1 a 5 por usuário); `pedidos_zipf` concentra a maioria dos pedidos em poucos usuários |
| [`um-para-um.yaml`](um-para-um.yaml) | `one_to_one` com `coverage: 0.7` | `perfis` tem exatamente `round(0.7 * 1000) = 700` linhas, com FK única |
| [`muitos-para-muitos.yaml`](muitos-para-muitos.yaml) | tabela ponte `pedido_produto` com PK `composite` | nenhum par `(pedido_id, produto_id)` se repete |
| [`cardinalidades.yaml`](cardinalidades.yaml) | `fixed`, `range`, `uniform` e `zipf` lado a lado | `filhos_fixed` tem exatamente `300` linhas (`100 * 3`); os demais variam conforme a distribuição |
| [`chaves.yaml`](chaves.yaml) | `sequence` (start/step), `seeded_int` e `seeded_uuid` | `sequencial.id` = `100, 110, 120, ...`; `embaralhada.id` é uma permutação de `[1, 500]`; `uuid.id` são UUIDs v4 válidos e únicos |
| [`fk-distribuicao.yaml`](fk-distribuicao.yaml) | FK não dirigente com `distribution: {zipf: ...}` e `shuffle: true` | `produtos.categoria_id` concentra-se em poucas categorias, sem correlação com a ordem do `id` da categoria |
| [`thread-estrutura.yaml`](thread-estrutura.yaml) | tabela `thread` (participantes, `start`, `gap_seconds`, bloco `llm` para a trilha C) | por `thread_id`: `seq` vai de `1..N`; `timestamp` estritamente crescente; nenhum `autor` repete o autor da mensagem anterior |

## Sobre `fixed` e `uniform` no YAML

O contrato de schema (DD-00 §3.3) expressa cardinalidade como
`{range: {min, max}, distribution: {zipf: {s}}}`. As formas `fixed(k)` e
`uniform(mean, spread)` do desenho da trilha B (§B.3.4) são **equivalentes**
a um `range`:

- `fixed(k)` = `range(min=k, max=k)`;
- `uniform(mean, spread)` = `range(min=mean-spread, max=mean+spread)`.

Por isso os exemplos acima escrevem sempre `range` no YAML; a API Python
(`dataipsum.relations.cardinality.sample`) aceita as 4 formas diretamente,
como `FixedCardinality`/`RangeCardinality`/`UniformCardinality`/
`ZipfCardinality` (ver `tests/relations/unit/test_cardinality.py`).

## Rodando os exemplos hoje

```bash
uv run python -c "
from dataipsum import load_schema, validate
from dataipsum.relations import RelationsPlanner
from dataipsum.schema.models import ValidationContext
schema = load_schema('examples/relacoes/um-para-muitos.yaml')
print(validate(schema, ValidationContext(planner=RelationsPlanner())))
"
```

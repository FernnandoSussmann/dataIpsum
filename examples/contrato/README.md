# Exemplos da área `contrato` (DD-02, trilha H)

Estes exemplos demonstram o **contrato** do schema dataIpsum: o mesmo
formato descrito em DD-00 §3.3, versionado como JSON Schema em
[`schemas/dataipsum-schema.v1.json`](../../schemas/dataipsum-schema.v1.json)
e consumível tanto pelo pacote Python quanto por ferramentas externas.
`tests/contract/test_examples.py` valida todo `examples/**/*.yaml` (incluindo
os `.yaml` desta pasta) com `dataipsum.validate`; `schema.json` é validado à
parte porque é JSON, não YAML.

| Arquivo | Demonstra | Comando | Saída esperada |
|---|---|---|---|
| [`schema.json`](schema.json) | O mesmo schema de [`examples/loja.yaml`](../loja.yaml), em **JSON** em vez de YAML — o contrato aceita os dois formatos porque `dataipsum.load_schema` faz `yaml.safe_load`, que é um superconjunto de JSON | `uv run python -c "from dataipsum import load_schema; print(load_schema('examples/contrato/schema.json').name)"` | `loja` |
| [`minimo.yaml`](minimo.yaml) | O menor schema válido: só os campos obrigatórios de topo, tabela e coluna | `uv run python -c "from dataipsum import load_schema, validate; print(validate(load_schema('examples/contrato/minimo.yaml')))"` | `ValidationReport(is_valid=True, errors=[])` |
| [`validar-com-jsonschema.sh`](validar-com-jsonschema.sh) | Validar um schema com uma ferramenta **externa** de JSON Schema (`check-jsonschema`), sem depender do pacote dataIpsum — prova que o contrato é consumível por qualquer cliente, como a futura UI web (DD-02 H.2) | `bash examples/contrato/validar-com-jsonschema.sh examples/contrato/schema.json` | `OK: schema válido segundo o contrato dataIpsum v1.` |

## Sobre `schema.json` e `examples/loja.yaml`

`examples/loja.yaml` é a **referência** usada em testes de várias trilhas
(DD-02 §0, H.3.4) e no S5 de integração: três tabelas (`usuarios`,
`produtos`, `pedidos`), uma relação `rows_from` (`pedidos` depende de
`usuarios` via `usuario_id`), uma coluna `llm_post` com a seção `llm`
correspondente, e colunas exercitando `null_ratio`, `invalid_ratio`,
`format` e `max_length`. `schema.json` é o mesmo conteúdo, só que serializado
como JSON — os dois validam com o mesmo `Schema.model_validate` e com o
mesmo JSON Schema publicado.

## Sobre o JSON Schema versionado

`schemas/dataipsum-schema.v1.json` é gerado por
`dataipsum.schema.jsonschema.export_json_schema()` (o que o comando
`dataipsum schema jsonschema` vai imprimir, DD-02 G.3.1) e versionado no
git. `tests/contract/unit/test_jsonschema_drift.py` garante que ele nunca
diverge do modelo Pydantic: qualquer mudança de contrato precisa regenerar o
arquivo e justificar a mudança pelas regras de compatibilidade em
[`docs/api/README.md`](../../docs/api/README.md).

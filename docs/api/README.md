# Contrato da API web (rascunho, DD-02 — trilha H, M4 só contrato)

O RESEARCH §2.10 põe a UI web (e a API FastAPI que a serviria) **fora do
MVP**. A única garantia deste marco é o **contrato**: o formato do schema
(YAML/JSON, versionado como JSON Schema) e o esboço de rotas HTTP que a UI
futura vai consumir. Nada neste diretório está implementado — não há
FastAPI, autenticação real, nem servidor rodando.

[`openapi.v1.yaml`](openapi.v1.yaml) é um rascunho estruturalmente válido de
OpenAPI 3.1 com as 7 rotas da tabela abaixo (DD-02 H.3.3), cada uma mapeada
para uma função da façade `dataipsum.api` (DD-00 §3.8), e a seção
`info.description` documenta os requisitos de segurança obrigatórios a
partir do M4.

## Rotas

| Método e rota | Função | Mapeia para |
|---|---|---|
| `POST /v1/schemas:validate` | valida um schema (corpo JSON) | `api.validate` |
| `POST /v1/plans` | calcula o plano (linhas por tabela, chunks) | `api.plan` |
| `POST /v1/runs` | inicia uma execução assíncrona | `api.generate` |
| `GET /v1/runs/{run_id}` | status e manifesto resumido | manifesto (DD-00 §3.7) |
| `POST /v1/runs/{run_id}:resume` | retoma | `api.resume` |
| `POST /v1/schemas:export` | DDL/Avro | `api.export_schema` |
| `POST /v1/schemas:import` | DDL → schema (M3) | `api.import_ddl` |

## Requisitos de segurança (obrigatórios a partir do M4)

- **Autenticação obrigatória** em toda rota, sem exceção.
- O cliente **nunca** informa caminhos de sistema de arquivos: o servidor
  escolhe o destino de cada execução por `run_id`, nunca por um caminho
  vindo do corpo da requisição.
- Limites de tamanho de corpo, de número de linhas planejadas e de execuções
  simultâneas por usuário, aplicados antes de qualquer processamento.
- Segredos do LLM e dos sinks (chaves de API, senhas, DSNs) só existem no
  servidor, como variáveis de ambiente (`*_env`, DD-00 §6.5); o corpo da
  requisição nunca aceita um segredo em si, só o nome de uma variável de
  ambiente já configurada no servidor.
- CORS restrito à origem da UI oficial.

Esses requisitos ficam registrados aqui como parte do contrato: quando a API
for implementada, ela nasce com eles, em vez de adicioná-los depois.

## O JSON Schema versionado

O corpo de `schema` em várias rotas (`PlanRequest.schema`,
`RunRequest.schema`, `ExportRequest.schema`, `ImportResult.schema`)
referencia
[`schemas/dataipsum-schema.v1.json`](../../schemas/dataipsum-schema.v1.json):
o JSON Schema exportado por `dataipsum.schema.jsonschema.export_json_schema()`
(o que `dataipsum schema jsonschema` imprime, DD-02 G.3.1) e versionado no
git (DD-02 H.3.1). `$id` é `https://dataipsum.local/schemas/dataipsum-schema.v1.json`:
um identificador estável, não uma URL resolvível.

`tests/contract/unit/test_jsonschema_drift.py` regenera o JSON Schema a
partir do modelo Pydantic e compara byte a byte com o arquivo versionado —
qualquer diferença falha o teste, e o PR que a introduziu precisa atualizar
o arquivo **e** justificar a mudança pelas regras abaixo.

## Regras de compatibilidade (DD-02 H.3.2)

- **Mudança aditiva** (campo opcional novo, com padrão que preserva o
  comportamento anterior) ⇒ o contrato continua `version: 1`, e o arquivo
  `dataipsum-schema.v1.json` é regenerado no lugar.
- **Mudança incompatível** (remover ou renomear um campo, mudar a semântica
  de um campo existente ou mudar um padrão) ⇒ o contrato vira `version: 2`,
  com um novo arquivo `schemas/dataipsum-schema.v2.json`. O loader mantém
  suporte a `version: 1` por pelo menos um marco, com um conversor v1 → v2.
- A UI deve **preservar campos desconhecidos** ao salvar um schema que ela
  não entende totalmente — isso é o que permite o round-trip entre versões
  menores do contrato. Esta regra fica documentada aqui para o M4; não há
  implementação de UI neste marco para aplicá-la.

## Validando um schema com o contrato publicado

Ver [`examples/contrato/`](../../examples/contrato/README.md): o mesmo
schema em JSON e em YAML, o menor schema válido, e um script que valida um
schema com uma ferramenta externa de JSON Schema (`check-jsonschema`), sem
depender do pacote Python dataIpsum.

## Stack sugerido para a UI futura (só registrado, fora de escopo)

React + React Flow, com um canvas estilo Miro/draw.io para desenhar tabelas
e relações. Nenhuma decisão de implementação foi tomada além de registrar a
sugestão do RESEARCH §2.10 — a trilha H não implementa FastAPI, autenticação,
React nem React Flow.

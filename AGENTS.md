# Data Ipsum
Esse é um projeto de um gerador de dados. Ele gera os dados de tabelas e outras estruturas podendo configurar uma certa quantidade de dados validos. Também algumas features se integram com LLMs.

## Estrutura
Pastas:
- docker: Contem a imagem Docker do projeto ou partes dela para compor uma imagem completa
- docs: Documentações da aplicação como a de API
- examples: Exemplos de uso e configurações de funcionalidades
- scripts: Utilitarios para execuções de operações ou verificações do projeto
    - check_security_exceptions.py: Valida `security/exceptions.yaml` e traduz exceções em argumentos por ferramenta
    - render_dockerfile.py: Monta o `Dockerfile` da raiz a partir de `docker/Dockerfile.in` e dos fragmentos por área
    - run_bandit.py: Roda `bandit` sobre `src`, com as exceções de §3.2.1 traduzidas para `--skip`
    - run_dependency_check.py: Roda OWASP Dependency-Check no `uv.lock`
    - run_pip_audit.py: Roda `pip-audit` sobre o `uv.lock` (base + extras + dev)
    - run_semgrep.py: Roda `semgrep` sobre `src`
- security: Possue configurações de segurança
- src/dataipsum: Raiz do projeto com alguns arquivos de utilidade geral     
    - cli: Ainda não implementado
    - contracts: Contratos de implementação dos diversos recursos do projeto
    - execution: Ainda não implementado
    - llm: Ainda não implementado
    - relations: Ainda não implementado
    - schema: 
    - schema_io: Ainda não implementado
    - sinks: Ainda não implementado
    - testing: Atualmente apenas com Mocks do projeto
    - types: Ainda não implementado
- tests: Possue testes relativos as implementações de `src/dataipsum`

## Guidelines
**Estilo funcional**
- Transformações de coleções usam `map`, `filter` e `functools.reduce`, ou os equivalentes idiomáticos (compreensões e expressões geradoras), no lugar de `for` com acumulador (`lista.append`, `total += ...`, `dict[k] = ...` dentro de laço).
- Funções são **puras** sempre que possível: sem efeito colateral e sem mutar argumentos. O resultado depende só das entradas.
- Estruturas imutáveis por padrão: `@dataclass(frozen=True)`, `tuple` e `frozenset`. Mutação é local e explícita.
- **Onde o laço explícito é aceito**, e só onde deixa o código mais claro:
  - **dados em volume** (colunas, chunks): prefira operações vetorizadas de `numpy`/`pyarrow` a `map` ou a laços por linha. Iterar linha a linha em Python dentro de geradores é proibido, porque a vetorização é requisito de algumas implementações;
  - **efeitos colaterais inerentemente sequenciais**: laço de retry com backoff, laço de eventos do driver/monitor, escrita em disco ou em rede.
**Comportamento explicito**
- Nomes de variáveis e funções devem refletir seu comportamento, sendo claro o funcionamento do projeto apenas lendo o código
- Comentários devem ser evitados e só devem aparecer quando algum comportamento não poder ser expressado pelo código. Exemplo: tratamento de dado especifico proveniente de resposta de serviço externo

## Guardrails
Toda nova implementação que altera código ou comportamento do projeto deve rodar testes, linter, verificação de segurança e demais verificações disponíveis. Se a alteração for grande testes de ponta a ponta devem ser executados OBRIGATORIAMENTE.

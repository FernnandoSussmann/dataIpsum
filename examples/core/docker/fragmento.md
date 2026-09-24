# Como uma trilha adiciona um fragmento à imagem Docker

Referência: DD-00 §3.12.2 e §3.12.3. Nenhuma trilha edita `docker/Dockerfile.in` nem o
`Dockerfile` gerado — só o par de fragmentos da própria área.

Exemplo: a trilha C (LLM, DD-01) precisa de um diretório gravável para cache de modelos e de
um preload opcional dos pesos de toxicidade.

## 1. Edite só os seus fragmentos

- `docker/fragments/llm.build.dockerfile`: passos que precisam do venv pronto, mas ainda no
  estágio `build` (ex.: baixar pesos de modelo para dentro da imagem).
- `docker/fragments/llm.runtime.dockerfile`: passos do estágio final, sempre executados
  **antes** de `USER 10001` (ex.: criar o diretório de cache e ajustar o dono).

```dockerfile
# docker/fragments/llm.build.dockerfile
ARG DATAIPSUM_TOXICITY_PRELOAD_ENV=""
RUN if [ -n "$DATAIPSUM_TOXICITY_PRELOAD_ENV" ]; then \
        python -m dataipsum.llm.preload_toxicity; \
    fi
```

```dockerfile
# docker/fragments/llm.runtime.dockerfile
RUN mkdir -p /work/_cache/llm \
    && chown 10001:10001 /work/_cache/llm
```

Lembre das restrições (validadas automaticamente, veja passo 2):

- só `ARG`, `ENV`, `RUN`, `COPY --from=build` e `LABEL` — nunca `FROM`, `USER`, `ENTRYPOINT`,
  `CMD`, `EXPOSE`, `VOLUME`, `SHELL`, `HEALTHCHECK` ou `ADD`;
- `RUN apt-get install` sempre com `--no-install-recommends` e limpeza de
  `/var/lib/apt/lists`;
- nenhum compilador (`gcc`, `g++`, `make`, `build-essential`) no fragmento `*.runtime`;
- `ENV`/`ARG` com nome parecido com segredo (`pass`, `secret`, `token`, `key`) só é aceito
  terminado em `_env` (ex.: `DATAIPSUM_TOXICITY_PRELOAD_ENV`, não `DATAIPSUM_TOXICITY_TOKEN`).

## 2. Rode o render e valide

```sh
uv run python scripts/render_dockerfile.py         # gera o Dockerfile a partir dos fragmentos
uv run python scripts/render_dockerfile.py --check  # confirma que não há divergência (CI/pre-commit)
git diff Dockerfile                                  # revise o que mudou antes do commit
```

Se um fragmento violar uma regra, o script recusa a montagem e aponta o arquivo e a instrução
ofensiva — nada é escrito em `Dockerfile`.

## 3. Escreva o teste da área

Cada mudança na imagem ganha um teste em `tests/docker/test_image_<área>.py`, marcado
`@pytest.mark.docker`, cobrindo o smoke test funcional da área (não repita os testes já
cobertos por `tests/docker/test_image_base.py`):

```python
# tests/docker/test_image_llm.py
import subprocess

import pytest

pytestmark = pytest.mark.docker


def test_diretorio_de_cache_e_gravavel_pelo_usuario_nao_root(image_com_llm: str) -> None:
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "sh",
            image_com_llm,
            "-c",
            "touch /work/_cache/llm/ok && echo gravavel",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "gravavel"
```

## 4. Descreva o impacto na imagem no PR

Toda descrição de PR com mudança na imagem tem a seção "Impacto na imagem" (DD-00 §3.12.3):
fragmentos alterados, extras exigidos, variáveis novas, volumes graváveis e o tamanho medido
antes/depois (os fixtures de `tests/docker/test_image_base.py` já imprimem o tamanho da
imagem em MiB durante o build).

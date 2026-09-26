# Trilha C (DD-01, llm): cache de modelos gravável para o classificador de toxicidade
# (DD-01 §C.10). `TORCH_HOME`/`HF_HOME` apontam para o mesmo diretório de `DATAIPSUM_MODEL_CACHE`
# porque o Detoxify baixa o checkpoint via `torch.hub` e o tokenizer via Hugging Face.
ARG PRELOAD_TOXICITY=0

ENV DATAIPSUM_MODEL_CACHE=/var/cache/dataipsum/models \
    TORCH_HOME=/var/cache/dataipsum/models \
    HF_HOME=/var/cache/dataipsum/models

# O diretório é criado sempre (para o `COPY --from=build` do fragmento de runtime nunca falhar
# por origem ausente); o download só acontece com `PRELOAD_TOXICITY=1` e `toxicity` em `EXTRAS`
# (o pacote `detoxify` já foi instalado pelo `uv sync` genérico do template, antes deste ponto).
# hadolint ignore=SC2086
RUN set -eu; \
    mkdir -p "$DATAIPSUM_MODEL_CACHE"; \
    case ",$EXTRAS," in \
        *,toxicity,*) has_toxicity=1 ;; \
        *) has_toxicity=0 ;; \
    esac; \
    if [ "$PRELOAD_TOXICITY" = "1" ] && [ "$has_toxicity" = "1" ]; then \
        .venv/bin/python -c "from detoxify import Detoxify; Detoxify('multilingual')"; \
    fi

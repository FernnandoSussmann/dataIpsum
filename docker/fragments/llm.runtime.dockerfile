# Trilha C (DD-01, llm): copia o cache de modelos pré-baixado (se houver) e garante que o
# diretório seja gravável pelo usuário 10001 mesmo com rootfs `read_only` (DD-01 §C.10).
COPY --from=build /var/cache/dataipsum/models /var/cache/dataipsum/models

ENV DATAIPSUM_MODEL_CACHE=/var/cache/dataipsum/models \
    TORCH_HOME=/var/cache/dataipsum/models \
    HF_HOME=/var/cache/dataipsum/models

RUN chown -R 10001:10001 /var/cache/dataipsum/models

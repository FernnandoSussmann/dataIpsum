# Plugin de exemplo: `exemplo_placa`

Pacote Python mínimo que registra um gerador externo (`exemplo_placa`) via o
grupo de entry points `dataipsum.generators`, sem tocar em nenhum arquivo do
core do dataIpsum (DD-00 §3.4).

## Instalar

A partir da raiz do repositório:

```bash
uv pip install -e examples/core/plugin
```

## Usar

Plugins externos só carregam com uma allowlist explícita (`DATAIPSUM_PLUGINS`).
Hoje (antes da CLI completa da trilha G, que lerá isso automaticamente via
`dataipsum.config.resolve_run_options`), o valor da variável de ambiente
precisa ser repassado explicitamente para `build_registry`:

```bash
# Sem a variável: o plugin é encontrado mas NÃO carrega, e um aviso é logado
# explicando como autorizá-lo.
uv run python -c "
import os
from dataipsum.registry import build_registry
r = build_registry(allow_plugins_env=os.environ.get('DATAIPSUM_PLUGINS'))
print('exemplo_placa' in r.generators)
"
# -> False

# Com o nome da distribuição na allowlist: carrega.
DATAIPSUM_PLUGINS=dataipsum-plugin-exemplo uv run python -c "
import os
from dataipsum.registry import build_registry
r = build_registry(allow_plugins_env=os.environ.get('DATAIPSUM_PLUGINS'))
print('exemplo_placa' in r.generators)
"
# -> True

# "*" libera todos os plugins encontrados.
DATAIPSUM_PLUGINS=* uv run python -c "
import os
from dataipsum.registry import build_registry
r = build_registry(allow_plugins_env=os.environ.get('DATAIPSUM_PLUGINS'))
print('exemplo_placa' in r.generators)
"
# -> True
```

Tentar registrar um gerador com o mesmo nome de um built-in (ou de outro
plugin) levanta `RegistryConflictError` — built-ins nunca podem ser
sobrescritos por um plugin.

## Desinstalar

```bash
uv pip uninstall dataipsum-plugin-exemplo
```

"""`dataipsum gen`: gera dados a partir de um SCHEMA (arquivo) ou de flags
inline (DD-02 §G.3.1). Só faz parsing, chama `dataipsum.api`/`dataipsum.config`
e formata a saída: nenhuma regra de negócio mora aqui.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import typer

from dataipsum import api
from dataipsum.cli._errors import fail, translate_errors
from dataipsum.cli._inline import load_schema_from_source, print_schema_and_exit
from dataipsum.cli._output import echo_progress, echo_run_result
from dataipsum.cli._run_options import build_run_options, run_with_interrupt_drain
from dataipsum.cli._secrets import parse_sink_options
from dataipsum.config import SinkConfig

SinkKind = Literal["csv", "json", "jsonl", "parquet", "postgres", "mysql", "kafka"]
ExecutorKind = Literal["local", "ray"]
LLMOnFailureKind = Literal["pending", "placeholder"]

_EMIT_SCHEMA_KINDS = ("ddl", "avro")


def _split_emit_schema(value: str | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    formats = tuple(item.strip() for item in value.split(",") if item.strip())
    invalid = sorted(set(formats) - set(_EMIT_SCHEMA_KINDS))
    if invalid:
        raise typer.BadParameter(
            f"'--emit-schema' inválido: {invalid}. Aceitos: {sorted(_EMIT_SCHEMA_KINDS)}"
        )
    return formats


def _build_cli_overrides(
    *,
    seed: int | None,
    chunk_size: int | None,
    max_rows: int | None,
    executor: str | None,
    ray_address: str | None,
    cpu_max: float | None,
    mem_max: float | None,
    emit_schema: str | None,
    dialect: str | None,
    llm_on_failure: str | None,
    cache_dir: Path | None,
    no_cache: bool,
    no_plugins: bool,
) -> dict[str, object]:
    return {
        "seed": seed,
        "chunk_size": chunk_size,
        "max_rows": max_rows,
        "executor": executor,
        # `ray_address` não tem campo correspondente em `RunOptions` (DD-00 §3.8)
        # enquanto a trilha D (Ray) não existir; guardado aqui só para o dia em
        # que `resolve_run_options` ganhar esse campo.
        "ray_address": ray_address,
        "cpu_max": cpu_max,
        "mem_max": mem_max,
        "emit_schema": _split_emit_schema(emit_schema),
        "dialect": dialect,
        "llm_on_failure": llm_on_failure,
        "cache_dir": None if no_cache else cache_dir,
        "no_plugins": no_plugins,
    }


def gen(
    schema_path: Annotated[
        Path | None,
        typer.Argument(
            help="Schema YAML/JSON. Omitido quando se usa --table/--rows/--col (geração inline)."
        ),
    ] = None,
    *,
    out: Annotated[Path, typer.Option("-o", "--out", help="Diretório de saída.")],
    table: Annotated[
        str | None, typer.Option("--table", help="Nome da tabela (modo inline, uma tabela só).")
    ] = None,
    rows: Annotated[
        int | None, typer.Option("--rows", help="Número de linhas (modo inline).")
    ] = None,
    col: Annotated[
        list[str],
        typer.Option("--col", help="Coluna inline 'nome:tipo[:pk][:chave=valor...]'. Repetível."),
    ] = [],
    print_schema: Annotated[
        bool, typer.Option("--print-schema", help="Imprime o YAML equivalente ao inline e sai.")
    ] = False,
    seed: Annotated[int | None, typer.Option("--seed", help="Seed determinística.")] = None,
    chunk_size: Annotated[
        int | None, typer.Option("--chunk-size", help="Linhas por chunk.")
    ] = None,
    max_rows: Annotated[
        int | None, typer.Option("--max-rows", help="Limite total de linhas geradas.")
    ] = None,
    fmt: Annotated[
        SinkKind, typer.Option("--format", help="Sink de saída (padrão parquet).")
    ] = "parquet",
    sink_opt: Annotated[
        list[str],
        typer.Option(
            "--sink-opt", help="Opção do sink 'chave=valor'. Repetível. Segredos: use '*_env'."
        ),
    ] = [],
    executor: Annotated[ExecutorKind | None, typer.Option("--executor", help="Executor.")] = None,
    ray_address: Annotated[
        str | None,
        typer.Option(
            "--ray-address", help="Endereço do cluster Ray (inerte até a trilha D existir)."
        ),
    ] = None,
    cpu_max: Annotated[float | None, typer.Option("--cpu-max", help="Teto de CPU (%).")] = None,
    mem_max: Annotated[float | None, typer.Option("--mem-max", help="Teto de memória (%).")] = None,
    emit_schema: Annotated[
        str | None,
        typer.Option("--emit-schema", help="Formatos a exportar, separados por vírgula: ddl,avro."),
    ] = None,
    dialect: Annotated[str | None, typer.Option("--dialect", help="Dialeto SQL do DDL.")] = None,
    llm_on_failure: Annotated[
        LLMOnFailureKind | None,
        typer.Option("--llm-on-failure", help="Comportamento quando o LLM falha."),
    ] = None,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Desliga o cache do LLM.")] = False,
    cache_dir: Annotated[
        Path | None, typer.Option("--cache-dir", help="Diretório de cache do LLM.")
    ] = None,
    no_plugins: Annotated[
        bool, typer.Option("--no-plugins", help="Ignora plugins de DATAIPSUM_PLUGINS.")
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Resumo final em JSON no stdout.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("-v", "--verbose", help="Mostra stack trace em erros.")
    ] = False,
    quiet: Annotated[
        bool, typer.Option("-q", "--quiet", help="Silencia o progresso no stderr.")
    ] = False,
) -> None:
    """Gera dados a partir de um SCHEMA (arquivo) ou de flags inline (--table/--rows/--col)."""
    with translate_errors(verbose=verbose, as_json=json_output, out_dir=out):
        schema = load_schema_from_source(schema_path, table, rows, col)
        if print_schema:
            raise print_schema_and_exit(schema)

        report = api.validate(schema)
        if not report.is_valid:
            message = "; ".join(f"{error.path}: {error.message}" for error in report.errors)
            raise fail(message, as_json=json_output)

        sink = SinkConfig(kind=fmt, options=parse_sink_options(sink_opt))
        cli_overrides = _build_cli_overrides(
            seed=seed,
            chunk_size=chunk_size,
            max_rows=max_rows,
            executor=executor,
            ray_address=ray_address,
            cpu_max=cpu_max,
            mem_max=mem_max,
            emit_schema=emit_schema,
            dialect=dialect,
            llm_on_failure=llm_on_failure,
            cache_dir=cache_dir,
            no_cache=no_cache,
            no_plugins=no_plugins,
        )
        options = build_run_options(
            out_dir=out, sink=sink, schema=schema, cli_overrides=cli_overrides
        )

        echo_progress(f"iniciando geração em '{out}'...", quiet=quiet)
        result = run_with_interrupt_drain(
            lambda: api.generate(schema, options), out_dir=out, schema=schema, options=options
        )
        echo_run_result(result, as_json=json_output)
        if result.status != "completed":
            raise fail(
                f"execução '{result.status}' com {result.pending_chunks} chunk(s) pendente(s). "
                f"Rode 'dataipsum resume {out}' para retomar.",
                as_json=json_output,
            )

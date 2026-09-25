"""Executor Ray (M2, extra opcional `[ray]`, DD-01 §D.3.6).

`ray` **não** é uma dependência obrigatória do pacote (`pyproject.toml` só declara
`ray[default]` no extra opcional `[ray]`; a trilha D não pode editar esse arquivo —
ver o relatório do worktree). Por isso o import é tardio (dentro de `__init__`, não
no topo do módulo): importar este módulo nunca falha sem `ray` instalado, só
instanciar `RayExecutor` falha, com uma mensagem clara.

Este é um M1 funcional só na parte que M2 pede como scaffolding testável sem
cluster: detecção da ausência do extra e a mensagem de erro. O agendamento por
recursos, o `NodeMonitor` distribuído, o `LLMSemaphore` com lease e a sonda de FS
compartilhado (§D.3.6) ficam para quando um cluster Ray real puder ser exercitado
neste worktree — o design abaixo já reflete o contrato alvo, mas os métodos que
dependem de um cluster vivo levantam `ExecutorError` até serem completados.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from dataipsum.errors import ExecutorError

if TYPE_CHECKING:
    from dataipsum.contracts.executor import ChunkResult, ChunkTask
    from dataipsum.execution.local_executor import RunChunk

logger = logging.getLogger("dataipsum.execution.ray")

_PRIVATE_ADDRESS_HINT = "auto"


def warn_if_public_ray_address(ray_address: str) -> None:
    """§D.5 item 6: avisa se `ray_address` aponta para um IP público (Ray não
    tem autenticação própria)."""
    if ray_address == _PRIVATE_ADDRESS_HINT:
        return
    host = urlparse(ray_address).hostname or ray_address.split(":")[0]
    try:
        is_public = not ipaddress.ip_address(host).is_private
    except ValueError:
        is_public = False  # hostname (ex.: DNS interno): não dá para avaliar sem resolver
    if is_public:
        logger.warning(
            "ray_address '%s' parece apontar para um IP público. O Ray não tem "
            "autenticação: use rede privada (DD-01 §D.5).",
            ray_address,
        )


@dataclass
class RayExecutor:
    """`Executor` (DD-00 §3.5) sobre um cluster Ray (M2). Requer o extra `[ray]`."""

    ray_address: str
    run_chunk: RunChunk
    llm_task_gpus: int = 0
    _concurrency: int = field(init=False, repr=False, default=1)
    _ray: Any = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        try:
            import ray  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ExecutorError(
                "executor 'ray' pedido, mas o pacote 'ray' não está instalado. "
                "Instale o extra opcional '[ray]' (`uv sync --extra ray`) para usá-lo."
            ) from exc
        warn_if_public_ray_address(self.ray_address)
        ray.init(address=self.ray_address, ignore_reinit_error=True)
        self._ray = ray
        self._concurrency = self._slots_from_live_nodes()

    def _slots_from_live_nodes(self) -> int:
        nodes = self._ray.nodes()
        alive_cpu_slots = sum(
            int(node.get("Resources", {}).get("CPU", 0)) for node in nodes if node.get("Alive")
        )
        return max(1, alive_cpu_slots)

    def submit(self, tasks: Iterable[ChunkTask]) -> Iterator[ChunkResult]:
        remote_run_chunk = self._ray.remote(max_retries=3)(self.run_chunk)
        futures = [remote_run_chunk.remote(task) for task in tasks]
        while futures:
            ready, futures = self._ray.wait(futures, num_returns=1)
            yield from self._ray.get(ready)

    def set_concurrency(self, n: int) -> None:
        self._concurrency = n

    @property
    def concurrency(self) -> int:
        return self._concurrency

    def shutdown(self, wait: bool) -> None:
        self._ray.shutdown()

    def llm_limiter(self, provider_name: str, max_concurrency: int) -> object:
        raise ExecutorError(
            "LLMSemaphore distribuído (ator Ray nomeado com lease) ainda não "
            "implementado; requer um cluster Ray vivo para ser exercitado (M2)."
        )

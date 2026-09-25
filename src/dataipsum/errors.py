"""Hierarquia de erros do dataIpsum (DD-00 §3.9). Mensagens em pt-BR, nunca com segredos."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationError:
    path: str
    message: str


class DataIpsumError(Exception):
    """Raiz de todos os erros do dataIpsum."""


class SchemaError(DataIpsumError):
    def __init__(self, errors: list[ValidationError]) -> None:
        self.errors = errors
        super().__init__("; ".join(f"{e.path}: {e.message}" for e in errors))


class RegistryConflictError(DataIpsumError):
    pass


class PluginNotAllowedError(DataIpsumError):
    pass


class PlanError(DataIpsumError):
    pass


class ManifestError(DataIpsumError):
    pass


class ManifestMismatchError(ManifestError):
    pass


class SinkError(DataIpsumError):
    pass


class ExecutorError(DataIpsumError):
    pass


class LLMError(DataIpsumError):
    pass


class ProviderUnavailable(LLMError):  # noqa: N818 -- nome exigido pelo contrato LLMProvider (§3.5)
    pass


class ProviderRateLimited(LLMError):  # noqa: N818 -- nome exigido pelo contrato LLMProvider (§3.5)
    pass


class ProviderRefusal(LLMError):  # noqa: N818 -- nome exigido pelo contrato LLMProvider (§3.5)
    pass


class ProviderBadResponse(LLMError):  # noqa: N818 -- nome exigido pelo contrato LLMProvider (§3.5)
    pass


class ResourceLimitError(DataIpsumError):
    pass


class OutputDirError(DataIpsumError):
    pass

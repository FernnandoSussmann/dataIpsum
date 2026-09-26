"""Trilha A (DD-01): geradores de tipos primitivos e campos com regra.

Registra os 17 geradores (`string`, `char`, `int`, `float`, `decimal`, `boolean`,
`date`, `time`, `timestamp`, `uuid`, `json`, `array`, `cpf`, `rg`,
`cartao_credito`, `nome_proprio`, `email`) e o locale `pt_BR`. Também expõe as
funções de validação reutilizáveis (`is_valid_cpf`, `is_valid_email`,
`is_valid_rg_sp`, `luhn_is_valid`, `card_brand`, DD-01 A.4).
"""

from __future__ import annotations

from typing import cast

from dataipsum.registry import Registry
from dataipsum.types.documents import (
    CartaoCreditoGenerator,
    CpfGenerator,
    RgGenerator,
    card_brand,
    is_valid_cpf,
    is_valid_rg_sp,
)
from dataipsum.types.locales import register as register_locales
from dataipsum.types.luhn import luhn_is_valid
from dataipsum.types.person import EmailGenerator, NomeProprioGenerator, is_valid_email
from dataipsum.types.primitives import (
    ArrayGenerator,
    BooleanGenerator,
    CharGenerator,
    DateGenerator,
    DecimalGenerator,
    FloatGenerator,
    IntGenerator,
    JsonGenerator,
    StringGenerator,
    TimeGenerator,
    TimestampGenerator,
    UuidGenerator,
)

__all__ = [
    "card_brand",
    "is_valid_cpf",
    "is_valid_email",
    "is_valid_rg_sp",
    "luhn_is_valid",
    "register",
]


def register(registry: Registry) -> None:
    """Registra os geradores built-in de tipo e o locale `pt_BR`."""
    register_locales(registry)
    locales = registry.locales

    # `Registry.register_generator` guarda um construtor de zero argumentos por
    # nome (`cls: type` na assinatura, mas qualquer `Callable[[], Generator]`
    # funciona em tempo de execução — ver `get_generator(name)()`, chamado
    # assim em todo este pacote). `locales`/`registry` fecham sobre os
    # geradores que precisam deles; o `cast` só ajusta a assinatura estática.
    registry.register_generator("string", cast(type, lambda: StringGenerator(locales=locales)))
    registry.register_generator("char", cast(type, lambda: CharGenerator(locales=locales)))
    registry.register_generator("int", IntGenerator)
    registry.register_generator("float", FloatGenerator)
    registry.register_generator("decimal", DecimalGenerator)
    registry.register_generator("boolean", BooleanGenerator)
    registry.register_generator("date", DateGenerator)
    registry.register_generator("time", TimeGenerator)
    registry.register_generator("timestamp", TimestampGenerator)
    registry.register_generator("uuid", UuidGenerator)
    registry.register_generator("json", cast(type, lambda: JsonGenerator(registry=registry)))
    registry.register_generator("array", cast(type, lambda: ArrayGenerator(registry=registry)))
    registry.register_generator("cpf", CpfGenerator)
    registry.register_generator("rg", RgGenerator)
    registry.register_generator("cartao_credito", CartaoCreditoGenerator)
    registry.register_generator(
        "nome_proprio", cast(type, lambda: NomeProprioGenerator(locales=locales))
    )
    registry.register_generator("email", cast(type, lambda: EmailGenerator(locales=locales)))

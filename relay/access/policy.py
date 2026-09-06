from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ProviderAccessPolicy:
    """Fail-closed legal/product switch, kept separate from paid entitlement."""

    sales_enabled: bool = False
    capabilities: Mapping[str, bool] | None = None

    def allows(self, capability: str, provider: str = "") -> bool:
        values = self.capabilities or {}
        provider_key = f"{capability}:{provider.strip().lower()}" if provider else ""
        if provider_key and provider_key in values:
            return bool(values[provider_key])
        return bool(values.get(capability, False))

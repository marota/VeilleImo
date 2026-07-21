"""Modèle de données d'une annonce immobilière."""
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class Listing:
    id: str
    source: str
    url: str = ""
    title: str = ""
    price: Optional[int] = None
    surface: Optional[float] = None
    rooms: Optional[int] = None
    quartier: str = ""
    agency: str = ""

    @property
    def price_per_m2(self) -> Optional[int]:
        if self.price and self.surface:
            return round(self.price / self.surface)
        return None

    def to_dict(self) -> dict:
        return asdict(self)

    def label(self) -> str:
        parts = []
        if self.surface:
            parts.append(f"{self.surface:g} m²")
        if self.rooms:
            parts.append(f"{self.rooms} p.")
        if self.price:
            parts.append(f"{self.price:,} €".replace(",", " "))
        if self.price_per_m2:
            parts.append(f"({self.price_per_m2:,} €/m²)".replace(",", " "))
        head = " · ".join(parts)
        tail = " — ".join(x for x in [self.agency, self.quartier] if x)
        return f"{head}  {tail}".strip()

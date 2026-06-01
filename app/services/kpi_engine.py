"""
app/services/kpi_engine.py
motor de calculo de kpis para posicoes de tags rtls
logica pura sem i/o — chamada por app/main.py
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from config import LIMIAR_MOVIMENTO_CM


@dataclass
class RegistoTag:
    """ponto de posicao de uma tag num instante"""
    tag_id: str
    x: float
    y: float
    timestamp: Optional[datetime] = None
    bateria: Optional[float] = None


@dataclass
class KpiTag:
    """kpis calculados para uma tag num periodo"""
    tag_id: str
    distancia_cm: float = 0.0
    leituras_totais: int = 0
    leituras_em_movimento: int = 0
    bateria_min: float = 100.0
    bateria_ultima: float = 0.0
    tempo_ocioso_seg: float = 0.0

    @property
    def distancia_m(self) -> float:
        return round(self.distancia_cm / 100, 2)

    @property
    def taxa_utilizacao_perc(self) -> float:
        if self.leituras_totais == 0:
            return 0.0
        return round((self.leituras_em_movimento / self.leituras_totais) * 100, 1)

    @property
    def bateria_min_perc(self) -> float:
        return round(self.bateria_min, 1) if self.bateria_min < 100.0 else 0.0


def calcular_kpis(
    registos: list[RegistoTag],
    limiar_movimento_cm: float = LIMIAR_MOVIMENTO_CM,
) -> dict[str, KpiTag]:
    """
    calcula kpis por tag a partir de registos ordenados cronologicamente.
    funcao pura — sem i/o, sem efeitos laterais.
    """
    tags: dict[str, KpiTag] = {}
    # ultimo ponto conhecido por tag: (x, y, timestamp)
    ultimas: dict[str, tuple[float, float, Optional[datetime]]] = {}

    for r in registos:
        if r.tag_id not in tags:
            kpi = KpiTag(tag_id=r.tag_id)
            if r.bateria is not None:
                kpi.bateria_min = r.bateria
                kpi.bateria_ultima = r.bateria
            tags[r.tag_id] = kpi

        kpi = tags[r.tag_id]
        kpi.leituras_totais += 1

        if r.bateria is not None:
            kpi.bateria_ultima = r.bateria
            if r.bateria < kpi.bateria_min:
                kpi.bateria_min = r.bateria

        if r.tag_id in ultimas:
            ux, uy, uts = ultimas[r.tag_id]
            dist = math.sqrt((r.x - ux) ** 2 + (r.y - uy) ** 2)
            kpi.distancia_cm += dist
            if dist > limiar_movimento_cm:
                kpi.leituras_em_movimento += 1
            elif uts is not None and r.timestamp is not None:
                kpi.tempo_ocioso_seg += max((r.timestamp - uts).total_seconds(), 0)

        ultimas[r.tag_id] = (r.x, r.y, r.timestamp)

    return tags

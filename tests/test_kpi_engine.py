"""
tests/test_kpi_engine.py
testa a logica pura de calculo de kpis (sem I/O)
"""

from datetime import datetime, timezone, timedelta

import pytest

from app.services.kpi_engine import RegistoTag, calcular_kpis


def _ts(segundos_atras: int = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=segundos_atras)


class TestRegistoTag:
    def test_registo_cria_com_campos_minimos(self):
        r = RegistoTag(tag_id="TAG1", x=100.0, y=200.0)
        assert r.tag_id == "TAG1"
        assert r.bateria is None

    def test_registo_com_todos_os_campos(self):
        r = RegistoTag(tag_id="TAG1", x=100.0, y=200.0, timestamp=_ts(), bateria=85.0)
        assert r.bateria == 85.0


class TestCalcularKpis:
    def test_sem_registos_devolve_dicionario_vazio(self):
        resultado = calcular_kpis([])
        assert resultado == {}

    def test_um_registo_por_tag_sem_distancia(self):
        r = [RegistoTag("T1", 0.0, 0.0, _ts(60))]
        kpis = calcular_kpis(r)
        assert "T1" in kpis
        assert kpis["T1"].distancia_cm == 0.0
        assert kpis["T1"].leituras_totais == 1

    def test_distancia_calculada_correctamente(self):
        # dois pontos a 100 cm de distancia (3-4-5 triangle: 60,80 -> 0,0)
        registos = [
            RegistoTag("T1", 0.0,  0.0,  _ts(120)),
            RegistoTag("T1", 60.0, 80.0, _ts(60)),   # distancia = 100 cm
        ]
        kpis = calcular_kpis(registos)
        assert abs(kpis["T1"].distancia_cm - 100.0) < 0.1
        assert abs(kpis["T1"].distancia_m - 1.0) < 0.01

    def test_movimento_conta_quando_acima_do_limiar(self):
        registos = [
            RegistoTag("T1", 0.0,   0.0,   _ts(120)),
            RegistoTag("T1", 200.0, 0.0,   _ts(60)),  # 200cm > limiar 50cm
        ]
        kpis = calcular_kpis(registos, limiar_movimento_cm=50.0)
        assert kpis["T1"].leituras_em_movimento == 1

    def test_repouso_nao_conta_como_movimento(self):
        registos = [
            RegistoTag("T1", 0.0, 0.0, _ts(120)),
            RegistoTag("T1", 5.0, 0.0, _ts(60)),   # 5cm < limiar 50cm
        ]
        kpis = calcular_kpis(registos, limiar_movimento_cm=50.0)
        assert kpis["T1"].leituras_em_movimento == 0

    def test_taxa_utilizacao_entre_0_e_100(self):
        registos = [
            RegistoTag("T1", 0.0,   0.0,   _ts(180)),
            RegistoTag("T1", 200.0, 0.0,   _ts(120)),
            RegistoTag("T1", 200.0, 5.0,   _ts(60)),   # repouso
        ]
        kpis = calcular_kpis(registos, limiar_movimento_cm=50.0)
        taxa = kpis["T1"].taxa_utilizacao_perc
        assert 0.0 <= taxa <= 100.0

    def test_bateria_minima_correcta(self):
        registos = [
            RegistoTag("T1", 0.0, 0.0, _ts(120), bateria=90.0),
            RegistoTag("T1", 0.0, 0.0, _ts(60),  bateria=30.0),
            RegistoTag("T1", 0.0, 0.0, _ts(0),   bateria=70.0),
        ]
        kpis = calcular_kpis(registos)
        assert kpis["T1"].bateria_min_perc == 30.0
        assert kpis["T1"].bateria_ultima == 70.0

    def test_multiplas_tags_isoladas(self):
        registos = [
            RegistoTag("T1", 0.0,   0.0, _ts(60)),
            RegistoTag("T1", 100.0, 0.0, _ts(30)),
            RegistoTag("T2", 500.0, 0.0, _ts(60)),
            RegistoTag("T2", 600.0, 0.0, _ts(30)),
        ]
        kpis = calcular_kpis(registos)
        assert "T1" in kpis
        assert "T2" in kpis
        assert abs(kpis["T1"].distancia_cm - 100.0) < 0.1
        assert abs(kpis["T2"].distancia_cm - 100.0) < 0.1

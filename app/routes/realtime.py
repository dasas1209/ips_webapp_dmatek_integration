"""
app/routes/realtime.py
rotas de posicoes em tempo real: /posicoes, /historico
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from config import INFLUX_BUCKET, INFLUX_ORG
from app.dependencies import aplicar_rate_limit
from app.services.database import get_db_connection
from app.services.influx_client import get_influx_client

router = APIRouter()


def _enriquecer_com_nomes(posicoes: list[dict], tenant_id: str) -> None:
    try:
        with get_db_connection() as conn:
            tags_db = conn.execute(
                "SELECT id_fisico, nome FROM tags WHERE cliente_id = ?", (tenant_id,)
            ).fetchall()
            nome_por_tag = {t["id_fisico"]: t["nome"] for t in tags_db}
    except Exception:
        nome_por_tag = {}
    for p in posicoes:
        p["nome"] = nome_por_tag.get(p["tag_id"], p["tag_id"])


@router.get("/posicoes", tags=["Real-Time"])
def obter_posicoes(tenant_id: str = Depends(aplicar_rate_limit)):
    """devolve ultima posicao conhecida de cada tag"""
    try:
        query = f"""
            from(bucket: "{INFLUX_BUCKET}")
            |> range(start: -1h)
            |> filter(fn: (r) => r["_measurement"] == "posicao_tag")
            |> filter(fn: (r) => r["tenant_id"] == "{tenant_id}")
            |> last()
            |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        """
        tabelas = get_influx_client().query_api().query(query)

        posicoes = []
        for tabela in tabelas:
            for linha in tabela.records:
                x = linha.values.get("coord_x")
                y = linha.values.get("coord_y")
                if x is None or y is None:
                    continue
                posicoes.append({
                    "tag_id":    linha.values.get("tag_id"),
                    "x":         x,
                    "y":         y,
                    "timestamp": linha.values.get("_time"),
                    "bateria":   linha.values.get("bateria") or 0,
                    "status":    linha.values.get("status") or "Urgency",
                })

        _enriquecer_com_nomes(posicoes, tenant_id)

        try:
            with get_db_connection() as conn:
                total_sql = conn.execute(
                    "SELECT COUNT(*) AS n FROM tags WHERE cliente_id = ?", (tenant_id,)
                ).fetchone()["n"]
        except Exception:
            total_sql = len(posicoes)

        return {
            "tenant_id":            tenant_id,
            "total_tags_detetadas": len(posicoes),
            "total_tags_sql":       total_sql,
            "dados":                posicoes,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao consultar posicoes: {exc}")


@router.get("/historico", tags=["Real-Time"])
def obter_historico(
    minutos_atras: int = Query(..., ge=1, le=480, description="Minutos a recuar (1-480)"),
    tenant_id: str = Depends(aplicar_rate_limit),
):
    """devolve posicoes num instante historico especifico"""
    try:
        query = f"""
            from(bucket: "{INFLUX_BUCKET}")
            |> range(start: -{minutos_atras}m10s, stop: -{minutos_atras}m)
            |> filter(fn: (r) => r["_measurement"] == "posicao_tag")
            |> filter(fn: (r) => r["tenant_id"] == "{tenant_id}")
            |> last()
            |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        """
        tabelas = get_influx_client().query_api().query(query)

        posicoes = []
        for tabela in tabelas:
            for linha in tabela.records:
                x = linha.values.get("coord_x")
                y = linha.values.get("coord_y")
                if x is None or y is None:
                    continue
                posicoes.append({
                    "tag_id":    linha.values.get("tag_id"),
                    "x":         x,
                    "y":         y,
                    "timestamp": linha.values.get("_time"),
                    "bateria":   linha.values.get("bateria") or 0,
                    "status":    linha.values.get("status") or "Urgency",
                })

        _enriquecer_com_nomes(posicoes, tenant_id)

        return {
            "tenant_id":            tenant_id,
            "total_tags_detetadas": len(posicoes),
            "dados":                posicoes,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao consultar historico: {exc}")

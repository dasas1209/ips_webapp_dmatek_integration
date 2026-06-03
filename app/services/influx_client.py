"""
app/services/influx_client.py
singleton do cliente influxdb partilhado entre modulos
"""

from influxdb_client import InfluxDBClient  # type: ignore

from config import INFLUX_ORG, INFLUX_TOKEN, INFLUX_URL

_cliente: InfluxDBClient | None = None


def get_influx_client() -> InfluxDBClient:
    """devolve cliente influxdb singleton — evita tcp/tls handshake por pedido"""
    global _cliente
    if _cliente is None:
        _cliente = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    return _cliente

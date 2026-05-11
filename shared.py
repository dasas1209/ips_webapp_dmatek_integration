"""
shared.py
utilitarios partilhados entre api_dmatek.py e escuta_dmatek.py
"""

import csv
from pathlib import Path


def carregar_matriz_clientes(caminho: Path | str | None = None) -> dict[str, str]:
    """
    le o ficheiro csv e devolve um mapeamento entre tags e tenants
    """
    if caminho is None:
        caminho = Path(__file__).parent / "matriz_clientes.csv"

    caminho = Path(caminho)
    matriz: dict[str, str] = {}

    if not caminho.exists():
        print(f"[AVISO] {caminho.name} não encontrado. A operar sem mapeamento de clientes.")
        return matriz

    try:
        with open(caminho, encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter=";")
            for linha in reader:
                tag    = linha.get("tag_id",    "").strip()
                tenant = linha.get("tenant_id", "").strip()
                if tag and tenant:
                    matriz[tag] = tenant
        print(f"[INFO] Matriz carregada: {len(matriz)} tag(s) mapeada(s).")
    except Exception as exc:
        print(f"[ERRO] Falha ao ler matriz de clientes: {exc}")

    return matriz

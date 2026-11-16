"""Pipeline ETL determinístico da série mensal de produção de veículos no Brasil.

Projeto Prático G2 - Linguagens de Programação (2026.2)
Autores: Marcelo Bernardes e Lucas Queiroz

Fonte: ANFAVEA, distribuída pelo Banco Central do Brasil (SGS, série 1373)
e republicada no Kaggle (leonardobern/valor-da-produo-de-automveis-no-brasil).

Uso:
    python -m src.etl

Etapas:
    extract   -> lê o CSV bruto (ou baixa da API pública do BCB se ele não existir)
    transform -> tipagem, validação, calendário completo e métricas derivadas
    load      -> grava Parquet + CSV comprimido e um relatório de qualidade (JSON)

Nenhuma etapa altera o arquivo bruto. Toda linha descartada ou imputada é
contabilizada no relatório de qualidade, garantindo rastreabilidade.
"""

from __future__ import annotations

import csv
import json
import logging
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
ARQ_BRUTO = RAIZ / "data" / "raw" / "bcdata.sgs.1373.csv"
DIR_PROCESSADO = RAIZ / "data" / "processed"
ARQ_PARQUET = DIR_PROCESSADO / "producao_veiculos.parquet"
ARQ_CSV_GZ = DIR_PROCESSADO / "producao_veiculos.csv.gz"
ARQ_QUALIDADE = DIR_PROCESSADO / "relatorio_qualidade.json"

# Recorte idêntico ao do arquivo publicado no Kaggle (359 meses).
PERIODO_INICIO = "1993-01-01"
PERIODO_FIM = "2022-11-01"
URL_BCB = (
    "https://api.bcb.gov.br/dados/serie/bcdata.sgs.1373/dados"
    "?formato=csv&dataInicial=01/01/1993&dataFinal=30/11/2022"
)

CODIFICACOES = ("utf-8-sig", "latin-1")
LIMITE_IQR = 1.5

log = logging.getLogger("etl")


# --------------------------------------------------------------------------- #
# Extract
# --------------------------------------------------------------------------- #
def baixar_bruto(destino: Path = ARQ_BRUTO, url: str = URL_BCB) -> Path:
    """Baixa a série da API aberta do BCB (sem autenticação) para data/raw."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    log.info("Arquivo bruto ausente; baixando de %s", url)
    with urllib.request.urlopen(url, timeout=60) as resposta:
        destino.write_bytes(resposta.read())
    return destino


def _ler_texto(caminho: Path) -> tuple[str, str]:
    """Decodifica o arquivo testando as codificações esperadas, em ordem."""
    dados = caminho.read_bytes()
    for codificacao in CODIFICACOES:
        try:
            return dados.decode(codificacao), codificacao
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("etl", dados, 0, 1, "codificação não reconhecida")


def extract(caminho: Path = ARQ_BRUTO) -> tuple[pd.DataFrame, dict]:
    """Lê o CSV bruto como texto, detectando codificação e separador.

    Todas as colunas chegam como ``str``: a conversão de tipos é feita de forma
    explícita em :func:`transform`, para que nada seja inferido em silêncio.
    """
    if not caminho.exists():
        baixar_bruto(caminho)

    texto, codificacao = _ler_texto(caminho)
    separador = csv.Sniffer().sniff(texto[:2048], delimiters=";,\t|").delimiter

    bruto = pd.read_csv(
        caminho,
        sep=separador,
        encoding=codificacao,
        dtype=str,
        quotechar='"',
        skipinitialspace=True,
    )
    bruto.columns = [c.strip().lower() for c in bruto.columns]

    faltantes = {"data", "valor"} - set(bruto.columns)
    if faltantes:
        raise ValueError(f"Colunas obrigatórias ausentes no bruto: {faltantes}")

    meta = {
        "arquivo_bruto": caminho.name,
        "codificacao": codificacao,
        "separador": separador,
        "linhas_brutas": int(len(bruto)),
    }
    log.info("Bruto lido: %s", meta)
    return bruto[["data", "valor"]], meta


# --------------------------------------------------------------------------- #
# Transform
# --------------------------------------------------------------------------- #
def _para_inteiro(serie: pd.Series) -> pd.Series:
    """Converte texto numérico em padrão brasileiro para inteiro anulável.

    Remove separador de milhar (ponto) e aceita vírgula decimal. Valores que
    não puderem ser convertidos viram ``<NA>`` e são contados no relatório.
    """
    limpo = (
        serie.str.strip()
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
    )
    return pd.to_numeric(limpo, errors="coerce").round().astype("Int64")


def tipar_e_validar(bruto: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Aplica tipos, remove linhas inválidas/duplicadas e completa o calendário."""
    df = pd.DataFrame(
        {
            "data": pd.to_datetime(
                bruto["data"].str.strip(), format="%d/%m/%Y", errors="coerce"
            ),
            "producao": _para_inteiro(bruto["valor"]),
        }
    )

    qualidade = {
        "datas_invalidas": int(df["data"].isna().sum()),
        "valores_invalidos": int(df["producao"].isna().sum()),
        "valores_negativos": int((df["producao"] < 0).sum()),
    }

    df = df.dropna(subset=["data"])
    df = df[df["producao"].isna() | (df["producao"] >= 0)]

    # Normaliza qualquer dia do mês para o primeiro dia (granularidade mensal).
    df["data"] = df["data"].dt.to_period("M").dt.to_timestamp()

    qualidade["duplicatas_removidas"] = int(df.duplicated("data").sum())
    df = df.drop_duplicates("data", keep="last").sort_values("data")

    df = df[(df["data"] >= PERIODO_INICIO) & (df["data"] <= PERIODO_FIM)]

    # Calendário mensal completo: meses ausentes aparecem como linha nula
    # (não são inventados) e ficam visíveis para a análise.
    calendario = pd.date_range(df["data"].min(), df["data"].max(), freq="MS")
    df = df.set_index("data").reindex(calendario).rename_axis("data").reset_index()
    qualidade["meses_ausentes"] = int(df["producao"].isna().sum())
    qualidade["linhas_finais"] = int(len(df))
    qualidade["periodo"] = [
        df["data"].min().strftime("%Y-%m"),
        df["data"].max().strftime("%Y-%m"),
    ]
    return df, qualidade


def media_movel_centrada_12m(serie: pd.Series) -> pd.Series:
    """Média móvel centrada 2x12, estimativa clássica de tendência mensal."""
    return serie.rolling(12, center=True).mean().rolling(2).mean().shift(-1)


def adicionar_metricas(df: pd.DataFrame) -> pd.DataFrame:
    """Cria as variáveis derivadas descritas em data/data_dictionary.md."""
    df = df.copy()
    producao = df["producao"].astype("float64")

    df["ano"] = df["data"].dt.year.astype("int16")
    df["mes"] = df["data"].dt.month.astype("int8")
    df["trimestre"] = df["data"].dt.quarter.astype("int8")

    df["media_movel_12m"] = producao.rolling(12).mean()
    df["acumulado_12m"] = producao.rolling(12).sum()
    df["var_mensal_pct"] = producao.pct_change(1, fill_method=None) * 100
    df["var_anual_pct"] = producao.pct_change(12, fill_method=None) * 100

    # Componente sazonal + irregular: produção dividida pela tendência.
    df["tendencia"] = media_movel_centrada_12m(producao)
    df["razao_tendencia"] = producao / df["tendencia"]

    # Índice sazonal: mediana da razão por mês (robusta a choques como abr/2020),
    # normalizada para média 100.
    sazonal = df.groupby("mes")["razao_tendencia"].median()
    sazonal = sazonal / sazonal.mean() * 100
    df["indice_sazonal"] = df["mes"].map(sazonal)

    # Série dessazonalizada e resíduo: desvio percentual frente a uma tendência
    # robusta (mediana móvel centrada de 13 meses), que não é arrastada por um
    # único mês extremo como acontece com a média móvel.
    df["producao_dessaz"] = producao / (df["indice_sazonal"] / 100)
    df["tendencia_robusta"] = df["producao_dessaz"].rolling(13, center=True).median()
    df["residuo_pct"] = (df["producao_dessaz"] / df["tendencia_robusta"] - 1) * 100

    # Outliers pela regra de Tukey (1,5 x IQR) aplicada ao resíduo.
    q1, q3 = df["residuo_pct"].quantile([0.25, 0.75])
    iqr = q3 - q1
    inferior, superior = q1 - LIMITE_IQR * iqr, q3 + LIMITE_IQR * iqr
    df["outlier"] = (df["residuo_pct"] < inferior) | (df["residuo_pct"] > superior)

    # Queda em relação ao pico histórico do acumulado em 12 meses.
    pico = df["acumulado_12m"].cummax()
    df["queda_do_pico_pct"] = (df["acumulado_12m"] / pico - 1) * 100

    colunas_2casas = [
        "media_movel_12m", "var_mensal_pct", "var_anual_pct", "tendencia",
        "indice_sazonal", "producao_dessaz", "tendencia_robusta", "residuo_pct",
        "queda_do_pico_pct",
    ]
    df[colunas_2casas] = df[colunas_2casas].round(2)
    df["razao_tendencia"] = df["razao_tendencia"].round(4)
    df["acumulado_12m"] = df["acumulado_12m"].round().astype("Int64")
    return df


def transform(bruto: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    df, qualidade = tipar_e_validar(bruto)
    df = adicionar_metricas(df)
    qualidade["outliers_sinalizados"] = int(df["outlier"].sum())
    return df, qualidade


# --------------------------------------------------------------------------- #
# Load
# --------------------------------------------------------------------------- #
def load(df: pd.DataFrame, relatorio: dict) -> None:
    DIR_PROCESSADO.mkdir(parents=True, exist_ok=True)
    df.to_parquet(ARQ_PARQUET, index=False)
    df.to_csv(
        ARQ_CSV_GZ,
        index=False,
        date_format="%Y-%m-%d",
        compression={"method": "gzip", "mtime": 0},  # mtime fixo: saída determinística
    )
    ARQ_QUALIDADE.write_text(
        json.dumps(relatorio, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    log.info("Gravado: %s, %s, %s", ARQ_PARQUET.name, ARQ_CSV_GZ.name, ARQ_QUALIDADE.name)


def carregar_processado() -> pd.DataFrame:
    """Atalho usado pelo notebook e pelos gráficos para ler o dado tratado."""
    return pd.read_parquet(ARQ_PARQUET)


def main() -> pd.DataFrame:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    bruto, meta = extract()
    df, qualidade = transform(bruto)
    load(df, {**meta, **qualidade})
    log.info("Qualidade: %s", qualidade)
    return df


if __name__ == "__main__":
    main()

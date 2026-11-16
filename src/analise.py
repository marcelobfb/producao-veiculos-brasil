"""Métricas agregadas e figuras do artigo (EDA reprodutível).

Uso:
    python -m src.analise

Saídas (todas derivadas de data/processed/producao_veiculos.parquet):
    docs/assets/metricas.json       -> números citados no artigo
    docs/assets/dados_graficos.js   -> séries consumidas pelos gráficos Plotly
    docs/assets/fig*.png            -> figuras estáticas em alta resolução
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from src.etl import RAIZ, carregar_processado

DIR_ASSETS = RAIZ / "docs" / "assets"
MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
AZUL, AZUL_CLARO, VERMELHO, CINZA = "#1d4ed8", "#60a5fa", "#dc2626", "#64748b"
QUEDA_MINIMA_EPISODIO = -10.0  # % em relação ao pico anterior do acumulado 12m


# --------------------------------------------------------------------------- #
# Métricas
# --------------------------------------------------------------------------- #
def totais_anuais(df: pd.DataFrame) -> pd.DataFrame:
    anual = df.groupby("ano")["producao"].agg(total="sum", meses="count").reset_index()
    anual["total"] = anual["total"].astype("int64")
    anual["completo"] = anual["meses"] == 12
    anual["var_pct"] = anual["total"].where(anual["completo"]).pct_change(fill_method=None) * 100
    return anual


def sazonalidade_por_periodo(df: pd.DataFrame) -> pd.DataFrame:
    """Índice sazonal (mediana da razão à tendência) recalculado por subperíodo."""
    faixas = pd.cut(
        df["ano"], [1992, 2002, 2012, 2022], labels=["1993-2002", "2003-2012", "2013-2022"]
    )
    tabela = df.groupby([faixas, "mes"], observed=True)["razao_tendencia"].median().unstack(0)
    tabela = tabela / tabela.mean() * 100
    tabela["1993-2022"] = df.groupby("mes")["indice_sazonal"].first()
    return tabela.round(1)


def episodios_de_queda(df: pd.DataFrame) -> pd.DataFrame:
    """Lista os ciclos de queda do acumulado em 12 meses abaixo do pico anterior.

    Cada episódio vai do pico até a recuperação desse mesmo nível (ou até o fim
    da série, se o nível não foi recuperado).
    """
    s = df.dropna(subset=["acumulado_12m"]).set_index("data")["acumulado_12m"].astype(float)
    pico_corrente = s.cummax()
    abaixo = s < pico_corrente
    grupos = (abaixo != abaixo.shift()).cumsum()[abaixo]

    linhas = []
    for _, trecho in s[abaixo].groupby(grupos):
        pico_data = s.index[s.index.get_loc(trecho.index[0]) - 1]
        pico_valor = s[pico_data]
        vale_data = trecho.idxmin()
        queda = (trecho.min() / pico_valor - 1) * 100
        if queda > QUEDA_MINIMA_EPISODIO:
            continue
        recuperou = trecho.index[-1] != s.index[-1]
        fim = s.index[s.index.get_loc(trecho.index[-1]) + 1] if recuperou else None
        meses = lambda a, b: (b.year - a.year) * 12 + b.month - a.month
        linhas.append(
            {
                "pico": pico_data.strftime("%Y-%m"),
                "pico_valor": int(pico_valor),
                "vale": vale_data.strftime("%Y-%m"),
                "vale_valor": int(trecho.min()),
                "queda_pct": round(queda, 1),
                "meses_ate_vale": meses(pico_data, vale_data),
                "recuperacao": fim.strftime("%Y-%m") if recuperou else None,
                "meses_ate_recuperar": meses(pico_data, fim) if recuperou else None,
            }
        )
    return pd.DataFrame(linhas)


CHOQUES = {
    # nome: (meses de referência pré-choque, primeiro mês do choque)
    "Crise financeira global (2008)": (("2008-07", "2008-09"), "2008-10"),
    "Pandemia de COVID-19 (2020)": (("2019-12", "2020-02"), "2020-03"),
}


def choques_mensais(df: pd.DataFrame) -> list[dict]:
    """Profundidade e duração de choques abruptos na série dessazonalizada.

    O nível de referência é a média dessazonalizada dos três meses anteriores
    ao choque; a recuperação é o primeiro mês em que esse nível é retomado.
    """
    s = df.set_index("data")["producao_dessaz"]
    bruto = df.set_index("data")
    saida = []
    for nome, ((ini, fim), inicio) in CHOQUES.items():
        referencia = s[ini:fim].mean()
        depois = s[inicio:]
        retomada = depois[depois >= referencia].index
        retomada = retomada[0] if len(retomada) else None
        janela = depois[: retomada] if retomada is not None else depois
        fundo = janela.idxmin()
        saida.append(
            {
                "choque": nome,
                "referencia_dessaz": round(float(referencia)),
                "fundo": fundo.strftime("%Y-%m"),
                "producao_no_fundo": int(bruto.loc[fundo, "producao"]),
                "queda_dessaz_pct": round(float((s[fundo] / referencia - 1) * 100), 1),
                "var_anual_no_fundo_pct": float(bruto.loc[fundo, "var_anual_pct"]),
                "retomada": retomada.strftime("%Y-%m") if retomada is not None else None,
                "meses_abaixo_da_referencia": (
                    (retomada.year - pd.Timestamp(inicio).year) * 12
                    + retomada.month - pd.Timestamp(inicio).month
                    if retomada is not None else None
                ),
            }
        )
    return saida


def calcular_metricas(df: pd.DataFrame) -> dict:
    anual = totais_anuais(df)
    completos = anual[anual["completo"]].set_index("ano")["total"]
    ano_pico = int(completos.idxmax())
    cagr = lambda a, b: ((completos[b] / completos[a]) ** (1 / (b - a)) - 1) * 100

    saz = df.groupby("mes")["indice_sazonal"].first()
    razoes = [g.dropna().to_numpy() for _, g in df.groupby("mes")["razao_tendencia"]]
    kruskal = stats.kruskal(*razoes)

    # Parcela da variância da razão à tendência explicada pelo mês (eta²).
    validos = df.dropna(subset=["razao_tendencia"])
    media_geral = validos["razao_tendencia"].mean()
    sq_total = ((validos["razao_tendencia"] - media_geral) ** 2).sum()
    por_mes = validos.groupby("mes")["razao_tendencia"]
    sq_entre = (por_mes.count() * (por_mes.mean() - media_geral) ** 2).sum()

    pico_12m = df.loc[df["acumulado_12m"].idxmax()]
    ultimo = df.iloc[-1]
    menor = df.loc[df["producao"].idxmin()]
    maior = df.loc[df["producao"].idxmax()]
    outliers = df[df["outlier"]]

    return {
        "periodo": [df["data"].min().strftime("%Y-%m"), df["data"].max().strftime("%Y-%m")],
        "n_meses": int(len(df)),
        "total_periodo": int(df["producao"].sum()),
        "descritivas": {
            "media": round(float(df["producao"].mean()), 0),
            "mediana": float(df["producao"].median()),
            "desvio_padrao": round(float(df["producao"].std()), 0),
            "cv_pct": round(float(df["producao"].std() / df["producao"].mean() * 100), 1),
            "q1": float(df["producao"].quantile(0.25)),
            "q3": float(df["producao"].quantile(0.75)),
            "minimo": {"data": menor["data"].strftime("%Y-%m"), "valor": int(menor["producao"])},
            "maximo": {"data": maior["data"].strftime("%Y-%m"), "valor": int(maior["producao"])},
        },
        "anual": {
            "primeiro_ano": {"ano": int(completos.index[0]), "total": int(completos.iloc[0])},
            "ano_pico": {"ano": ano_pico, "total": int(completos[ano_pico])},
            "multiplo_pico_sobre_1993": round(float(completos[ano_pico] / completos.iloc[0]), 2),
            "cagr_1993_pico_pct": round(float(cagr(1993, ano_pico)), 2),
            "cagr_2003_2013_pct": round(float(cagr(2003, 2013)), 2),
            "var_2013_2016_pct": round(float((completos[2016] / completos[2013] - 1) * 100), 1),
            "var_2019_2020_pct": round(float((completos[2020] / completos[2019] - 1) * 100), 1),
            "var_2021_sobre_2019_pct": round(float((completos[2021] / completos[2019] - 1) * 100), 1),
            "total_2021": int(completos[2021]),
        },
        "acumulado_12m": {
            "pico": {"data": pico_12m["data"].strftime("%Y-%m"), "valor": int(pico_12m["acumulado_12m"])},
            "ultimo": {
                "data": ultimo["data"].strftime("%Y-%m"),
                "valor": int(ultimo["acumulado_12m"]),
                "queda_do_pico_pct": float(ultimo["queda_do_pico_pct"]),
            },
        },
        "sazonalidade": {
            "indice": {MESES[m - 1]: float(v) for m, v in saz.items()},
            "amplitude_pontos": round(float(saz.max() - saz.min()), 1),
            "kruskal_h": round(float(kruskal.statistic), 1),
            "kruskal_p": float(kruskal.pvalue),
            "eta2_pct": round(float(sq_entre / sq_total * 100), 1),
            "por_periodo": sazonalidade_por_periodo(df).rename(index=lambda m: MESES[m - 1]).to_dict(),
        },
        "outliers": {
            "total": int(len(outliers)),
            "negativos": int((outliers["residuo_pct"] < 0).sum()),
            "limites_pct": [
                round(float(df.loc[~df["outlier"], "residuo_pct"].min()), 1),
                round(float(df.loc[~df["outlier"], "residuo_pct"].max()), 1),
            ],
            "lista": [
                {"data": r.data.strftime("%Y-%m"), "producao": int(r.producao), "residuo_pct": float(r.residuo_pct)}
                for r in outliers.itertuples()
            ],
        },
        "episodios": json.loads(episodios_de_queda(df).to_json(orient="records")),
        "choques": choques_mensais(df),
    }


# --------------------------------------------------------------------------- #
# Dados para os gráficos interativos (Plotly.js no artigo)
# --------------------------------------------------------------------------- #
def exportar_dados_graficos(df: pd.DataFrame, metricas: dict) -> None:
    anual = totais_anuais(df)
    nulo = lambda s: [None if pd.isna(v) else float(v) for v in s]
    matriz = df.pivot(index="ano", columns="mes", values="producao")
    dados = {
        "datas": df["data"].dt.strftime("%Y-%m-%d").tolist(),
        "producao": nulo(df["producao"]),
        "media_movel_12m": nulo(df["media_movel_12m"]),
        "queda_do_pico_pct": nulo(df["queda_do_pico_pct"]),
        "residuo_pct": nulo(df["residuo_pct"]),
        "outlier": df["outlier"].tolist(),
        "anual": {
            "ano": anual["ano"].tolist(),
            "total": anual["total"].tolist(),
            "completo": anual["completo"].tolist(),
        },
        "meses": MESES,
        "indice_sazonal": list(metricas["sazonalidade"]["indice"].values()),
        "heatmap": {"anos": matriz.index.tolist(), "z": [nulo(l) for l in matriz.to_numpy()]},
        "metricas": metricas,
    }
    conteudo = "window.DADOS = " + json.dumps(dados, ensure_ascii=False, separators=(",", ":")) + ";\n"
    (DIR_ASSETS / "dados_graficos.js").write_text(conteudo, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Figuras estáticas (matplotlib)
# --------------------------------------------------------------------------- #
def _estilo() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 100, "savefig.dpi": 200, "savefig.bbox": "tight",
            "font.family": "DejaVu Sans", "font.size": 10,
            "axes.spines.top": False, "axes.spines.right": False,
            "axes.edgecolor": "#cbd5e1", "axes.grid": True, "grid.color": "#e2e8f0",
            "axes.axisbelow": True, "axes.titleweight": "bold", "axes.titlelocation": "left",
        }
    )


def _milhares(ax, eixo="y") -> None:
    fmt = plt.FuncFormatter(lambda v, _: f"{v / 1000:,.0f}".replace(",", "."))
    (ax.yaxis if eixo == "y" else ax.xaxis).set_major_formatter(fmt)


def fig_serie(df: pd.DataFrame) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(df["data"], df["producao"], color=AZUL_CLARO, lw=1, alpha=0.75, label="Produção mensal")
    ax.plot(df["data"], df["media_movel_12m"], color=AZUL, lw=2.2, label="Média móvel de 12 meses")
    _milhares(ax)
    ax.set(title="Produção mensal de veículos no Brasil (1993-2022)", ylabel="Mil unidades", xlabel="")
    ax.legend(frameon=False, loc="upper left")
    return fig


def fig_anual(df: pd.DataFrame) -> plt.Figure:
    anual = totais_anuais(df)
    fig, ax = plt.subplots(figsize=(10, 4.2))
    cores = [AZUL if c else "#93c5fd" for c in anual["completo"]]
    ax.bar(anual["ano"], anual["total"] / 1e6, color=cores, width=0.75)
    ax.set(title="Produção anual de veículos (2022: jan-nov)", ylabel="Milhões de unidades", xlabel="")
    ax.grid(axis="x", visible=False)
    return fig


def fig_boxplot_mensal(df: pd.DataFrame) -> plt.Figure:
    dados = [g.dropna().to_numpy() * 100 for _, g in df.groupby("mes")["razao_tendencia"]]
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.axhline(100, color=CINZA, lw=1, ls="--")
    ax.boxplot(
        dados, tick_labels=MESES, patch_artist=True, widths=0.6,
        boxprops=dict(facecolor="#bfdbfe", edgecolor=AZUL),
        medianprops=dict(color=AZUL, lw=2), whiskerprops=dict(color=AZUL),
        capprops=dict(color=AZUL),
        flierprops=dict(marker="o", markersize=4, markerfacecolor=VERMELHO, markeredgecolor="none", alpha=0.7),
    )
    ax.set(
        title="Distribuição da razão produção/tendência por mês do ano",
        ylabel="Produção em % da tendência (100 = tendência)", xlabel="",
    )
    ax.grid(axis="x", visible=False)
    return fig


def fig_heatmap(df: pd.DataFrame) -> plt.Figure:
    matriz = df.pivot(index="ano", columns="mes", values="producao").astype(float) / 1000
    fig, ax = plt.subplots(figsize=(8.5, 9))
    imagem = ax.imshow(matriz, aspect="auto", cmap="Blues")
    ax.set_xticks(range(12), MESES)
    ax.set_yticks(range(len(matriz)), matriz.index)
    ax.grid(False)
    ax.set_title("Produção mensal por ano e mês (mil unidades)")
    fig.colorbar(imagem, ax=ax, shrink=0.6, label="Mil unidades")
    return fig


def fig_queda(df: pd.DataFrame) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.fill_between(df["data"], df["queda_do_pico_pct"], 0, color=AZUL_CLARO, alpha=0.35)
    ax.plot(df["data"], df["queda_do_pico_pct"], color=AZUL, lw=1.5)
    ax.set(title="Distância do pico histórico (acumulado em 12 meses)", ylabel="% abaixo do pico", xlabel="")
    return fig


def fig_residuos(df: pd.DataFrame) -> plt.Figure:
    fora = df[df["outlier"]]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.axhline(0, color=CINZA, lw=1)
    ax.plot(df["data"], df["residuo_pct"], color=AZUL_CLARO, lw=1, label="Resíduo dessazonalizado")
    ax.scatter(fora["data"], fora["residuo_pct"], color=VERMELHO, s=28, zorder=3, label="Outlier (1,5 x IQR)")
    ax.set(title="Desvio da produção dessazonalizada frente à tendência", ylabel="% da tendência", xlabel="")
    ax.legend(frameon=False, loc="lower left")
    return fig


FIGURAS = {
    "fig1_serie_mensal.png": fig_serie,
    "fig2_producao_anual.png": fig_anual,
    "fig3_boxplot_sazonal.png": fig_boxplot_mensal,
    "fig4_heatmap_ano_mes.png": fig_heatmap,
    "fig5_queda_do_pico.png": fig_queda,
    "fig6_residuos_outliers.png": fig_residuos,
}


def main() -> dict:
    DIR_ASSETS.mkdir(parents=True, exist_ok=True)
    df = carregar_processado()
    metricas = calcular_metricas(df)
    (DIR_ASSETS / "metricas.json").write_text(
        json.dumps(metricas, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    exportar_dados_graficos(df, metricas)
    _estilo()
    for nome, funcao in FIGURAS.items():
        figura = funcao(df)
        figura.savefig(DIR_ASSETS / nome)
        plt.close(figura)
    print(f"Métricas, dados dos gráficos e {len(FIGURAS)} figuras gravados em {DIR_ASSETS}")
    return metricas


if __name__ == "__main__":
    main()

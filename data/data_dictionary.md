# Dicionário de Dados

**Projeto:** Ciclos, Sazonalidade e Choques na Produção de Veículos no Brasil (1993-2022)
**Autores:** Marcelo Bernardes e Lucas Queiroz
**Disciplina:** Linguagens de Programação (2026.2), Bacharelado em Sistemas de Informação, UniLaSalle Rio de Janeiro

## 1. Proveniência

| Item | Descrição |
|---|---|
| Fonte primária | Associação Nacional dos Fabricantes de Veículos Automotores (ANFAVEA) |
| Distribuidor | Banco Central do Brasil, SGS, série **1373** (Produção de veículos, total) |
| Cópia utilizada | Kaggle: <https://www.kaggle.com/datasets/leonardobern/valor-da-produo-de-automveis-no-brasil> |
| API aberta (sem autenticação) | <https://api.bcb.gov.br/dados/serie/bcdata.sgs.1373/dados?formato=csv&dataInicial=01/01/1993&dataFinal=30/11/2022> |
| Cobertura temporal | janeiro de 1993 a novembro de 2022 (359 meses) |
| Cobertura geográfica | Brasil (total nacional) |
| Granularidade | 1 linha = 1 mês |
| Unidade de medida | unidades de veículos produzidos |

> **Atenção:** o título do dataset no Kaggle fala em "valor da produção", mas a coluna `valor` contém
> **quantidade física** (unidades), e não valor monetário.

## 2. Arquivo bruto: `data/raw/bcdata.sgs.1373.csv`

Formato: CSV, codificação UTF-8, separador `;`, todos os campos entre aspas duplas, quebra de linha CRLF, 1 linha de cabeçalho e 359 linhas de dados.

| Variável | Significado | Tipo no arquivo | Formato | Exemplo |
|---|---|---|---|---|
| `data` | Mês de referência da produção (sempre o dia 1) | texto | `dd/mm/aaaa` | `"01/04/2020"` |
| `valor` | Total de veículos produzidos no mês | texto numérico | inteiro sem separador de milhar | `"1847"` |

## 3. Arquivo tratado: `data/processed/producao_veiculos.parquet` (e `.csv.gz`)

Gerado por `python -m src.etl`. Contém 359 linhas e 17 variáveis. No CSV, datas em ISO 8601 (`aaaa-mm-dd`), ponto como separador decimal e vírgula como separador de campos.

| Variável | Significado de negócio/pesquisa | Tipo | Unidade / formato | Nulos |
|---|---|---|---|---|
| `data` | Mês de referência (primeiro dia do mês) | `datetime64` | `aaaa-mm-dd` | 0 |
| `producao` | Veículos produzidos no mês (coluna `valor` do bruto) | `Int64` | unidades | 0 |
| `ano` | Ano de referência | `int16` | 1993 a 2022 | 0 |
| `mes` | Mês de referência | `int8` | 1 a 12 | 0 |
| `trimestre` | Trimestre civil | `int8` | 1 a 4 | 0 |
| `media_movel_12m` | Média da produção nos 12 meses encerrados no mês; suaviza a sazonalidade | `float64` | unidades | 11 (início) |
| `acumulado_12m` | Soma da produção nos 12 meses encerrados no mês; base da análise de ciclos | `Int64` | unidades | 11 (início) |
| `var_mensal_pct` | Variação frente ao mês anterior | `float64` | % | 1 |
| `var_anual_pct` | Variação frente ao mesmo mês do ano anterior | `float64` | % | 12 |
| `tendencia` | Tendência estimada por média móvel centrada 2x12 | `float64` | unidades | 12 (6 em cada extremo) |
| `razao_tendencia` | `producao / tendencia`; componente sazonal + irregular | `float64` | razão (1 = tendência) | 12 |
| `indice_sazonal` | Mediana de `razao_tendencia` do mês, normalizada para média 100; constante para cada mês do ano | `float64` | índice (100 = tendência) | 0 |
| `producao_dessaz` | Produção dessazonalizada: `producao / (indice_sazonal / 100)` | `float64` | unidades | 0 |
| `tendencia_robusta` | Mediana móvel centrada de 13 meses de `producao_dessaz`; não é distorcida por um mês extremo | `float64` | unidades | 12 |
| `residuo_pct` | Desvio de `producao_dessaz` frente a `tendencia_robusta` | `float64` | % | 12 |
| `outlier` | `True` se `residuo_pct` está além de 1,5 x IQR (regra de Tukey) | `bool` | `True`/`False` | 0 |
| `queda_do_pico_pct` | Distância de `acumulado_12m` em relação ao seu máximo histórico até o mês (0 = novo recorde) | `float64` | % (≤ 0) | 11 |

Os nulos das variáveis derivadas são estruturais: decorrem das janelas móveis nas bordas da série e não representam dado faltante na fonte.

## 4. Regras de qualidade aplicadas

Resultados gravados em `data/processed/relatorio_qualidade.json`.

| Regra | Tratamento | Ocorrências nesta base |
|---|---|---|
| Data fora do formato `dd/mm/aaaa` | linha descartada e contada | 0 |
| Valor não numérico | convertido em nulo e contado | 0 |
| Valor negativo | linha descartada e contada | 0 |
| Mês duplicado | mantida a última ocorrência; duplicatas contadas | 0 |
| Mês ausente no calendário | linha criada com `producao` nula (sem imputação) | 0 |
| Outlier estatístico | **mantido** e sinalizado na coluna `outlier` | 16 |

## 5. Outliers documentados

Meses sinalizados pela regra de Tukey (ver `docs/assets/metricas.json` para os valores):

- **Negativos (10):** jan/1995, nov/1998, dez/1998, ago/2003, nov/2008, dez/2008, abr/2020, mai/2020, jun/2020, jul/2020.
- **Positivos (6):** jun/1995, mai/2001, set/2014, dez/2020, jan/2021, dez/2021.

São eventos reais (crises e retomadas), não erros de medição, e por isso permanecem na base.

## 6. Artefatos derivados

| Arquivo | Conteúdo |
|---|---|
| `docs/assets/metricas.json` | Métricas agregadas citadas no artigo |
| `docs/assets/dados_graficos.js` | Séries usadas pelos gráficos interativos (Plotly.js) |
| `docs/assets/fig*.png` | Figuras estáticas (200 dpi) |

# Ciclos, Sazonalidade e Choques na Produção de Veículos no Brasil (1993-2022)

![Python](https://img.shields.io/badge/Python-3.13-blue)
![pandas](https://img.shields.io/badge/pandas-3.0.5-150458)
![Licença código](https://img.shields.io/badge/c%C3%B3digo-MIT-green)
![Licença texto e dados](https://img.shields.io/badge/texto%20e%20dados-CC--BY%204.0-lightgrey)
![FAIR](https://img.shields.io/badge/FAIR-compliant-1e3a8a)

| | |
|---|---|
| **Autores** | Marcelo Bernardes e Lucas Queiroz |
| **Instituição** | UniLaSalle Rio de Janeiro, Bacharelado em Sistemas de Informação |
| **Disciplina** | Linguagens de Programação (Análise e Visualização de Dados com Python), 6º período |
| **Semestre** | 2026.2 |
| **Docente** | Prof. Alexandre Neves Louzada |
| **Artefato** | Projeto Prático G2 |

**Artigo publicado (GitHub Pages):** <https://marcelobfb.github.io/producao-veiculos-brasil/>

## Resumo executivo

Este projeto analisa a série mensal de produção de veículos automotores no Brasil, divulgada pela ANFAVEA e distribuída pelo Banco Central do Brasil (SGS 1373), com 359 meses entre janeiro de 1993 e novembro de 2022. Um pipeline determinístico em Python lê o arquivo bruto, valida tipos e continuidade, deriva métricas de tendência, sazonalidade e resíduo, e gera as figuras e o artigo acadêmico em HTML.

Principais achados:

- **Ciclos longos (RQ1).** A produção anual foi de 1,17 milhão (1993) para o recorde de 3,71 milhões (2013), caiu 41,4% até 2016 e terminou a série 36,7% abaixo do pico (acumulado em 12 meses).
- **Sazonalidade significativa (RQ2).** Janeiro, fevereiro e dezembro ficam de 10% a 16% abaixo da tendência; agosto e março, cerca de 10% acima (Kruskal-Wallis, p < 0,001).
- **Choques de formas diferentes (RQ3).** Abril de 2020 teve apenas 1.847 unidades, o choque mais profundo e mais curto. A retração iniciada em 2013 é a mais longa e não havia sido revertida até novembro de 2022.

**Palavras-chave:** indústria automotiva; séries temporais; sazonalidade; análise exploratória de dados; Python; princípios FAIR.

## Perguntas de pesquisa

1. **RQ1.** Como a produção de veículos evoluiu entre 1993 e 2022, e quais ciclos de expansão e retração podem ser identificados?
2. **RQ2.** Existe um padrão sazonal sistemático na produção mensal? Ele se manteve estável ao longo das três décadas?
3. **RQ3.** Qual foi a profundidade e a duração dos grandes choques (1998-1999, 2008-2009, 2014-2016 e 2020), e quais meses se comportam como outliers?

## Fonte dos dados

| Item | Link |
|---|---|
| Dataset utilizado (Kaggle) | <https://www.kaggle.com/datasets/leonardobern/valor-da-produo-de-automveis-no-brasil> |
| Série original (BCB, SGS 1373) | <https://api.bcb.gov.br/dados/serie/bcdata.sgs.1373/dados?formato=json> |
| Fonte primária | ANFAVEA: <https://anfavea.com.br/site/edicoes-em-excel/> |

O arquivo bruto (`data/raw/bcdata.sgs.1373.csv`, 8 kB) está versionado no repositório. Se ele for apagado, `src/etl.py` baixa a mesma série da API aberta do Banco Central, sem autenticação.

> A coluna `valor` contém **unidades produzidas**, e não valor monetário, apesar do título do dataset no Kaggle. Detalhes em [`data/data_dictionary.md`](data/data_dictionary.md).

## Estrutura do repositório

```
producao-veiculos-brasil/
├── README.md
├── LICENSE                       # MIT (código)
├── LICENSE-CC-BY-4.0.md          # CC-BY 4.0 (texto, figuras e dados derivados)
├── requirements.txt              # dependências com versões fixadas (pip freeze)
├── .gitignore
├── data/
│   ├── raw/bcdata.sgs.1373.csv           # dado bruto original (nunca alterado)
│   ├── processed/
│   │   ├── producao_veiculos.parquet     # dado tratado (tipagem preservada)
│   │   ├── producao_veiculos.csv.gz      # mesmo conteúdo em CSV comprimido
│   │   └── relatorio_qualidade.json      # contagem de inconsistências tratadas
│   └── data_dictionary.md                # dicionário de variáveis (FAIR)
├── notebooks/
│   └── analise_exploratoria.ipynb        # exploração e validação
├── src/
│   ├── __init__.py
│   ├── etl.py                            # extract, transform, load
│   └── analise.py                        # métricas, figuras e dados dos gráficos
└── docs/                                 # artigo servido pelo GitHub Pages
    ├── index.html
    └── assets/                           # figuras, métricas e dados dos gráficos
```

## Como reproduzir

Requisitos: Python 3.13 e Git.

```bash
# 1. Clonar
git clone https://github.com/marcelobfb/producao-veiculos-brasil.git
cd producao-veiculos-brasil

# 2. Ambiente virtual
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. ETL: data/raw -> data/processed
python -m src.etl

# 4. Métricas, figuras e dados dos gráficos -> docs/assets
python -m src.analise

# 5. (Opcional) Reexecutar o notebook
jupyter nbconvert --to notebook --execute --inplace notebooks/analise_exploratoria.ipynb

# 6. Ver o artigo localmente
python -m http.server --directory docs 8000    # http://localhost:8000
```

O pipeline é determinístico: duas execuções seguidas geram arquivos idênticos em `data/processed/` e `docs/assets/`.

## Pipeline em resumo

| Etapa | O que faz | Onde |
|---|---|---|
| **Extract** | Detecta codificação e separador; lê tudo como texto | `etl.extract` |
| **Transform** | Converte data (`%d/%m/%Y`) e produção (`Int64`); conta e trata inválidos, negativos e duplicatas; completa o calendário mensal; cria 15 métricas derivadas | `etl.transform` |
| **Load** | Grava Parquet, CSV gzip e relatório de qualidade | `etl.load` |
| **Análise** | Totais anuais, índice sazonal por período, ciclos de queda, choques, outliers; figuras e dados para Plotly | `analise.main` |

Nenhuma operação é destrutiva: o bruto não é alterado, linhas descartadas são contadas no relatório de qualidade e outliers são apenas sinalizados.

## Aderência aos princípios FAIR

| Princípio | Como é atendido |
|---|---|
| **Findable** | README com resumo, palavras-chave, autoria, disciplina, semestre e instituição; links perenes para a fonte |
| **Accessible** | Repositório público; ingestão sem credenciais; artigo no GitHub Pages, responsivo |
| **Interoperable** | `data/data_dictionary.md`; dados em Parquet e CSV gzip; datas em ISO 8601 |
| **Reusable** | Licenças MIT e CC-BY 4.0; `requirements.txt` congelado; instruções de execução |

## Publicação no GitHub Pages

No GitHub: **Settings > Pages > Build and deployment > Source: Deploy from a branch**, branch `main`, pasta `/docs`.

## Como citar

> BERNARDES, Marcelo; QUEIROZ, Lucas. **Ciclos, sazonalidade e choques na produção de veículos no Brasil (1993-2022)**: uma análise exploratória reprodutível em Python. Rio de Janeiro: UniLaSalle, 2026. Disponível em: https://github.com/marcelobfb/producao-veiculos-brasil.

## Licenças

- Código (`src/`, `notebooks/`): [MIT](LICENSE)
- Texto, figuras e dados derivados: [CC-BY 4.0](LICENSE-CC-BY-4.0.md)
- Dado bruto: série pública da ANFAVEA distribuída pelo Banco Central do Brasil; cite a fonte original.

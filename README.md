# ⚽ Brasileirão Série A — Analytics & Scouting BI (End-to-End com IA)

> **Contexto para Agentes de IA e Desenvolvedores:** Este documento é a fonte única da verdade (*Single Source of Truth*) deste projeto. Ele define a arquitetura de dados, o contrato de schemas (Star Schema), as regras de negócio em DAX e o blueprint visual das páginas no Power BI (`.pbip`).

---

## 🎯 1. Visão Geral do Projeto

Dashboard analítico interativo do **Campeonato Brasileiro Série A**, construído como projeto de portfólio e laboratório de engenharia de dados/BI assistida por Inteligência Artificial.

* **Fonte de Dados:** [API-Football](https://www.api-football.com/) (`league_id = 71`).
* **Orquestração & ETL:** Python + GitHub Actions (execução agendada na nuvem gratuita, gerando CSVs limpos na pasta `/data`).
* **Ingestão & Modelagem:** Power Query (M) consumindo os CSVs via URL bruta (`raw.githubusercontent.com`) em um modelo **Star Schema**.
* **Visualização:** Power BI Desktop salvo em formato **PBIP** (*Power BI Project*) com automação de layout e temas.

---

## 🏗️ 2. Arquitetura e Fluxo de Dados

```text
[API-Football (REST JSON)]
        │
        ▼  (GitHub Actions - Cron 2x/semana + Manual Dispatch)
[Script Python ETL (src/extract.py)]
        │  - Respeita rate limit da API gratuita
        │  - Normaliza grão de partidas e jogadores
        ▼
[Repositório GitHub (/data/*.csv)]
        │
        ▼  (Power Query - Web.Contents)
[Power BI (.pbip) - Modelo Star Schema + DAX]
        │
        ▼
[Dashboard 4 Páginas (1280x720)]
```

### Regras de Infraestrutura
* **Segurança:** A chave `API_FOOTBALL_KEY` deve ser armazenada exclusivamente em **GitHub Secrets**, nunca hardcoded no script ou no `.pbip`.
* **Consumo no Power Query:** Apontar diretamente para os arquivos `.csv` do branch `main` para evitar chamadas paginadas diretas na API dentro do Power BI e prevenir erros de *Dynamic Data Source* no Power BI Service.

---

## 🗄️ 3. Contrato de Dados (Star Schema)

O pipeline Python deve gerar **4 arquivos CSV** na pasta `/data`, que serão transformados nas tabelas abaixo dentro do Power BI:

### 3.1. Tabelas Dimensão

#### `dClubes` (Origem: `/data/clubes.csv`)
| Coluna | Tipo | Descrição / Regra |
| :--- | :--- | :--- |
| `id_clube` | Int64 | **Chave Primária (PK)** — ID oficial da API. |
| `nome_clube` | Text | Nome padronizado do clube. |
| `sigla` | Text | Sigla de 3 letras (ex: FLA, PAL, SAO). |
| `escudo_url` | Text | URL do logo oficial (*Data Category: Image URL*). |
| `estadio` | Text | Nome do estádio mandante. |
| `cidade` | Text | Cidade sede do clube. |

#### `dJogadores` (Origem: `/data/jogadores.csv`)
| Coluna | Tipo | Descrição / Regra |
| :--- | :--- | :--- |
| `id_jogador` | Int64 | **Chave Primária (PK)** — ID oficial do atleta. |
| `nome_jogador` | Text | Nome curto/apelido esportivo. |
| `nome_completo` | Text | Nome completo do atleta. |
| `idade` | Int64 | Idade na temporada. |
| `nacionalidade` | Text | País de origem. |
| `posicao` | Text | Traduzida: `Goleiro`, `Defensor`, `Meio-Campo`, `Atacante`. |
| `foto_url` | Text | URL da foto oficial (*Data Category: Image URL*). |

#### `dJogador_A` e `dJogador_B` (Tabelas Calculadas / Referência no Power Query)
* **Regra Arquitetural:** Cópias exatas de `dJogadores`, mantidas **sem relacionamento** com as tabelas fato (tabelas desconectadas).
* **Finalidade:** Alimentar os seletores independentes da **Página 4 (Head-to-Head)** via função DAX `TREATAS`.

#### `dRodadas` (Origem: derivada de `fPartidas` ou `/data/rodadas.csv`)
| Coluna | Tipo | Descrição / Regra |
| :--- | :--- | :--- |
| `rodada_num` | Int64 | **Chave Primária (PK)** — Número da rodada (`1` a `38`). |
| `rodada_label` | Text | Rótulo formatado (`"Rodada 01"` ... `"Rodada 38"`). |
| `turno` | Text | `"1º Turno"` (rodadas 1–19) ou `"2º Turno"` (rodadas 20–38). |

---

### 3.2. Tabelas Fato

#### `fPartidas` (Origem: `/data/partidas.csv`)
* **Granularidade:** 1 linha por **clube por partida** (cada jogo gera 2 registros: um como `Mandante` e outro como `Visitante`). Isso simplifica cálculos de classificação, mando de campo e pontuação acumulada.

| Coluna | Tipo | Descrição / Regra |
| :--- | :--- | :--- |
| `id_partida` | Int64 | ID único do confronto na API. |
| `rodada_num` | Int64 | **FK** -> `dRodadas[rodada_num]`. |
| `data_jogo` | Date | Data da realização da partida. |
| `id_clube` | Int64 | **FK** -> `dClubes[id_clube]` (time analisado na linha). |
| `id_adversario` | Int64 | ID do clube oponente. |
| `mando` | Text | `"Mandante"` ou `"Visitante"`. |
| `status_jogo` | Text | Código de status (`"FT"` = encerrado, `"NS"` = não iniciado). |
| `gols_pro` | Int64 | Gols marcados pelo `id_clube`. |
| `gols_contra` | Int64 | Gols sofridos pelo `id_clube`. |
| `pontos` | Int64 | `3` (Vitória), `1` (Empate), `0` (Derrota). |
| `resultado` | Text | `"V"`, `"E"` ou `"D"`. |

#### `fEstatisticasJogador` (Origem: `/data/estatisticas_jogadores.csv`)
* **Granularidade:** 1 linha por **jogador por clube na temporada** (atletas transferidos entre clubes da Série A durante o campeonato terão uma linha por clube).

| Coluna | Tipo | Descrição / Regra |
| :--- | :--- | :--- |
| `id_jogador` | Int64 | **FK** -> `dJogadores[id_jogador]`. |
| `id_clube` | Int64 | **FK** -> `dClubes[id_clube]`. |
| `jogos` | Int64 | Partidas em que entrou em campo. |
| `titularidades` | Int64 | Partidas iniciadas como titular. |
| `minutos_jogados` | Int64 | Total de minutos em campo. |
| `nota_media` | Decimal | Rating médio na competição (`0.00` a `10.00`). |
| `gols` | Int64 | Total de gols marcados. |
| `assistencias` | Int64 | Total de assistências para gol. |
| `finalizacoes_total` | Int64 | Total de chutes tentados. |
| `finalizacoes_no_gol` | Int64 | Chutes no alvo. |
| `passes_total` | Int64 | Total de passes tentados. |
| `passes_precisao_pct` | Decimal | Percentual de acerto de passes (`0.0` a `1.0`). |
| `passes_chave` | Int64 | Passes que geraram finalização (*Key Passes*). |
| `desarmes` | Int64 | Total de desarmes (*Tackles*). |
| `interceptacoes` | Int64 | Total de interceptações. |
| `cartoes_amarelos` | Int64 | Total de cartões amarelos. |
| `cartoes_vermelhos` | Int64 | Total de cartões vermelhos. |

---

## 📐 4. Especificação de Medidas DAX (`_Medidas`)

Todas as medidas devem residir em uma tabela dedicada `_Medidas`, organizadas em *Display Folders*:

### Pasta `01. Campeonato`
* **`Pontos Totais`** = `SUM(fPartidas[pontos])`
* **`Jogos Disputados`** = `CALCULATE(COUNTROWS(fPartidas), fPartidas[status_jogo] = "FT")`
* **`Vitórias`** = `CALCULATE(COUNTROWS(fPartidas), fPartidas[resultado] = "V", fPartidas[status_jogo] = "FT")`
* **`Empates`** = `CALCULATE(COUNTROWS(fPartidas), fPartidas[resultado] = "E", fPartidas[status_jogo] = "FT")`
* **`Derrotas`** = `CALCULATE(COUNTROWS(fPartidas), fPartidas[resultado] = "D", fPartidas[status_jogo] = "FT")`
* **`Gols Pró`** = `SUM(fPartidas[gols_pro])`
* **`Gols Contra`** = `SUM(fPartidas[gols_contra])`
* **`Saldo de Gols`** = `[Gols Pró] - [Gols Contra]`
* **`Aproveitamento %`** = `DIVIDE([Pontos Totais], [Jogos Disputados] * 3, 0)`
* **`Média Gols/Jogo`** = `DIVIDE([Gols Pró], [Jogos Disputados], 0)`
* **`Pontos Acumulados`** = 
  ```dax
  CALCULATE(
      [Pontos Totais],
      FILTER(
          ALLSELECTED(dRodadas[rodada_num]),
          dRodadas[rodada_num] <= MAX(dRodadas[rodada_num])
      )
  )
  ```

### Pasta `02. Jogadores`
* **`Minutos Jogados`** = `SUM(fEstatisticasJogador[minutos_jogados])`
* **`Gols`** = `SUM(fEstatisticasJogador[gols])`
* **`Assistências`** = `SUM(fEstatisticasJogador[assistencias])`
* **`Participações em Gol (G+A)`** = `[Gols] + [Assistências]`
* **`Nota Média`** = `AVERAGE(fEstatisticasJogador[nota_media])`
* **`Gols por 90min`** = `DIVIDE([Gols] * 90, [Minutos Jogados], 0)`
* **`Assistências por 90min`** = `DIVIDE([Assistências] * 90, [Minutos Jogados], 0)`
* **`G+A por 90min`** = `DIVIDE([Participações em Gol (G+A)] * 90, [Minutos Jogados], 0)`
* **`Conversão de Chutes %`** = `DIVIDE([Gols], SUM(fEstatisticasJogador[finalizacoes_total]), 0)`
* **`Precisão de Passe %`** = `AVERAGE(fEstatisticasJogador[passes_precisao_pct])`
* **`Desarmes`** = `SUM(fEstatisticasJogador[desarmes])`

### Pasta `03. Head-to-Head` (Padrão `TREATAS`)
Para cada métrica comparada (`Nota Média`, `Gols por 90min`, `Assistências por 90min`, `Participações em Gol (G+A)`, `Precisão de Passe %`, `Desarmes`, `Minutos Jogados`), criar o par `(A)` e `(B)`:
* **`[Métrica] (A)`** = `CALCULATE([Métrica], TREATAS(VALUES(dJogador_A[id_jogador]), fEstatisticasJogador[id_jogador]))`
* **`[Métrica] (B)`** = `CALCULATE([Métrica], TREATAS(VALUES(dJogador_B[id_jogador]), fEstatisticasJogador[id_jogador]))`
* **`Diff [Métrica] (A - B)`** = `[Métrica] (A) - [Métrica] (B)`

---

## 🎨 5. Blueprint Visual por Página (Canvas `1280 × 720`)

* **Diretrizes de UI/UX:** Tema escuro ou claro moderno com contraste alto, navegação superior/lateral fixa via botões nativos de página (evitar bookmarks), cards com cantos arredondados e hierarquia clara entre KPIs macro e tabelas analíticas.

### Página 1: `01. Visão Geral` (Panorama do Campeonato)
* **Filtros:** Turno (`dRodadas[turno]`), Mando (`fPartidas[mando]`).
* **KPI Cards (Topo):** Líder (Clube + Pontos), Aproveitamento do Líder %, Média de Gols/Jogo, Melhor Ataque (Clube + Gols).
* **Visuais:**
  1. **Tabela de Classificação (Esquerda):** Posição (RANKX), Escudo, Clube, P, J, V, E, D, GP, GC, SG, Aproveitamento % (com barra de dados).
  2. **Gráfico de Linhas (Direita Superior):** `Pontos Acumulados` por `dRodadas[rodada_num]` (Top 5 clubes ou clubes filtrados).
  3. **Gráfico de Barras Agrupadas (Direita Inferior):** `Aproveitamento %` por Clube quebrado por `Mando` (Mandante vs. Visitante).

### Página 2: `02. Scouting & Eficiência` (Análise Individual)
* **Filtros:** Clube (`dClubes[nome_clube]`), Posição (`dJogadores[posicao]`), Slicer Numérico de **Minutagem Mínima** (padrão `>= 450` min).
* **KPI Cards (Topo):** Artilheiro, Líder em Assistências, Maior Nota Média, Líder em `G+A por 90min`.
* **Visuais:**
  1. **Gráfico de Dispersão (Esquerda):** Eixo X = `Finalizações Totais` | Eixo Y = `Gols` | Tamanho = `Minutos Jogados` (com linhas constantes de média nos eixos X e Y).
  2. **Gráfico de Barras Horizontais Empilhadas (Direita):** Top 10 jogadores por `Participações em Gol (G+A)` (`Gols` + `Assistências`).
  3. **Tabela Analítica (Inferior):** Foto, Jogador, Clube, Posição, Jogos, Minutos, Nota Média, Gols, Assist., `G+A/90`, `Conversão %`.

### Página 3: `03. Raio-X do Clube` (Análise por Equipe)
* **Filtro Principal:** Slicer de seleção única para `dClubes[nome_clube]` + Card visual com Escudo e Estádio.
* **KPI Cards (Topo):** Posição Atual, Pontos, Aproveitamento %, Gols Pró, Gols Contra.
* **Visuais:**
  1. **Gráfico de Colunas/Linhas (Esquerda):** Desempenho por `rodada_num` (`Gols Pró` vs. `Gols Contra` ou pontos conquistados na rodada).
  2. **Tabela do Elenco (Direita):** Ordenada por `Minutos Jogados` descrescente (Foto, Jogador, Posição, Jogos, Titularidades, Minutos, Nota Média, Gols, Assistências, Cartões Amarelos/Vermelhos).

### Página 4: `04. Head-to-Head` (Comparativo Jogador A vs. Jogador B)
* **Topo Esquerdo:** Slicer `dJogador_A[nome_jogador]` + Card de perfil (Foto, Escudo do Clube, Posição, Idade, Minutos).
* **Topo Direito:** Slicer `dJogador_B[nome_jogador]` + Card de perfil (Foto, Escudo do Clube, Posição, Idade, Minutos).
* **Centro:** Gráfico de Barras Agrupadas ou Divergentes comparando lado a lado: `Nota Média`, `Gols/90`, `Assistências/90`, `Passes Chave`, `Precisão Passe %` e `Desarmes`.
* **Inferior:** Matriz/Tabela comparativa exibindo `Jogador A` | `Métrica` | `Jogador B` com formatação condicional destacando o vencedor de cada indicador.

---

## 📁 6. Estrutura de Pastas do Repositório

```text
brasileirao-bi-analytics/
├── .github/
│   └── workflows/
│       └── update_data.yml      # Automação GitHub Actions
├── data/
│   ├── clubes.csv               # Dimensão de clubes
│   ├── jogadores.csv            # Dimensão de atletas
│   ├── partidas.csv             # Fato de partidas (2 linhas/jogo)
│   └── estatisticas_jogadores.csv # Fato de stats individuais
├── powerbi/
│   ├── Brasileirao_Analytics.pbip
│   ├── Brasileirao_Analytics.Report/
│   └── Brasileirao_Analytics.SemanticModel/
├── src/
│   └── extract.py               # Script de consumo da API-Football
├── requirements.txt             # requests, pandas
└── README.md                    # Esta documentação
```

---

## 🚀 7. Status e Roadmap de Implementação

- [x] Definição de arquitetura, contrato de dados (Star Schema) e blueprint de 4 páginas.
- [ ] **Fase 1:** Implementar `src/extract.py` e `.github/workflows/update_data.yml` + validar chave da API-Football.
- [ ] **Fase 2:** Configurar ingestão via Power Query, relacionamentos Star Schema e medidas DAX no `.SemanticModel`.
- [ ] **Fase 3:** Construir tema JSON e gerar layout das 4 páginas no `.Report`.
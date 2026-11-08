# MCP Anti-Fraude

Servidor MCP em Python que analisa transações financeiras em tempo real e
detecta potenciais fraudes através de três regras heurísticas.

## Ferramenta disponível

### `analisar_risco_transacao`

Recebe o JSON de uma transação, compara contra o histórico em memória do
mesmo `associado_id` e retorna um score de risco de **0 a 100** com as
regras violadas.

#### Campos do JSON de entrada

Os campos marcados com ⬜ são **opcionais** — a sua presença enriquece a análise e as mensagens ao associado, mas a ferramenta funciona normalmente sem eles.

| Campo             | Tipo   | Obrigatório | Descrição                                                      |
|-------------------|--------|-------------|----------------------------------------------------------------|
| `transacao_id`    | string | ✅          | Identificador único da transação                               |
| `associado_id`    | string | ✅          | Identificador do associado/portador                            |
| `valor`           | float  | ✅          | Valor em R$                                                    |
| `categoria`       | string | ✅          | Categoria do estabelecimento (MCC)                             |
| `timestamp`       | string | ✅          | Data/hora ISO-8601 UTC (ex: `2026-11-02T15:30:00Z`)            |
| `latitude`        | float  | ⬜          | Coordenada geográfica do estabelecimento (regra GPS)           |
| `longitude`       | float  | ⬜          | Coordenada geográfica do estabelecimento (regra GPS)           |
| `cidade`          | string | ⬜          | Nome da cidade da transação (ex: `"Porto Alegre"`)             |
| `estado`          | string | ⬜          | Sigla do estado/UF ou subdivisão (ex: `"RS"`)                  |
| `pais`            | string | ⬜          | Código ISO 3166-1 alpha-2 do país (ex: `"BR"`, `"JP"`)         |
| `data_hora_local` | string | ⬜          | Data/hora no fuso do estabelecimento (ex: `"2026-11-02T12:30:00-03:00"`) |
| `fuso_horario`    | string | ⬜          | Fuso IANA do local (ex: `"America/Sao_Paulo"`, `"Asia/Tokyo"`) |

> **Compatibilidade:** `cidade`, `estado`, `pais`, `latitude` e `longitude` também são aceitos dentro de um sub-objeto `"localizacao": {…}`. A ferramenta nivela automaticamente via `_nivelar_localizacao()`.

#### Exemplo de chamada

```json
{
  "transacao_id": "tx_999",
  "associado_id": "assoc_001",
  "valor": 4500.00,
  "categoria": "Eletrônicos",
  "timestamp": "2026-11-02T05:15:00Z",
  "cidade": "Rio de Janeiro",
  "estado": "RJ",
  "pais": "BR",
  "data_hora_local": "2026-11-02T02:15:00-03:00",
  "fuso_horario": "America/Sao_Paulo",
  "latitude": -22.9068,
  "longitude": -43.1729
}
```

#### Exemplo de retorno

```json
{
  "transacao_id": "tx_999",
  "associado_id": "assoc_001",
  "score_risco": 100,
  "nivel_risco": "CRITICO",
  "regras_violadas": [
    {
      "regra": "VELOCIDADE_IMPOSSIVEL",
      "descricao": "Transação em localização geograficamente impossível dado o intervalo de tempo",
      "detalhe": "Distância de 358.3 km em 25.0 min (860 km/h) entre a transação t005 (São Paulo, SP, BR) e esta compra (Rio de Janeiro, RJ, BR)"
    },
    {
      "regra": "PICO_TRANSACAO",
      "descricao": "Valor 3.0x acima da média histórica do associado",
      "detalhe": "Valor R$ 4500.00 é 34.9x acima da média histórica (R$ 129.10)"
    },
    {
      "regra": "PERFIL_INCOMUM",
      "descricao": "Categoria de alto risco em horário incomum",
      "detalhe": "Categoria 'Eletrônicos' em horário incomum (02:15h — fora de 06h-22h)"
    }
  ],
  "historico_usado": 5,
  "localizacao_resumo": "Rio de Janeiro, RJ, BR",
  "data_hora_exibicao": "02/11/2026 às 02:15  (America/Sao_Paulo)"
}
```

## Ferramenta disponível

### `explicar_risco_fraude`

Gera uma explicação em **linguagem natural, sem jargões técnicos**, sobre por que uma transação foi sinalizada. Recebe o JSON retornado por `analisar_risco_transacao` e produz mensagens prontas para exibir ao associado via push/SMS ou ao analista no painel.

Quando `localizacao_resumo` e `data_hora_exibicao` estão presentes no JSON de entrada (campos produzidos por `analisar_risco_transacao`), as mensagens geradas incluem cidade, estado e data/hora local de forma contextualizada — ex: *"… antes desta compra em Rio de Janeiro, RJ"* ou *"02/11/2026 às 02:15 (America/Sao_Paulo)"*.

---

## Regras heurísticas

### 1. Velocidade Impossível (GPS)
Detecta compras em localidades geograficamente distantes realizadas em um
intervalo ≤ 30 minutos. A velocidade média necessária para percorrer a
distância é calculada e, se superar **600 km/h**, a regra é disparada.
Quando os campos `cidade`/`estado`/`pais` estão disponíveis, o detalhe técnico
inclui o nome dos dois locais — ex: `"… entre a transação t005 (São Paulo, SP, BR) e esta compra (Rio de Janeiro, RJ, BR)"`.
Contribui com **45 pontos** no score.

### 2. Pico de Transação
O valor da transação atual é comparado com a **média histórica** de gastos
do associado. Se o valor for ≥ **3× a média**, a regra é disparada.
Contribui com **35 pontos** no score.

### 3. Perfil Incomum
Transações em **categorias de alto risco** realizadas **fora do horário
comercial** (antes das 06h ou após as 22h) são sinalizadas.

Categorias monitoradas: Joalherias, Eletrônicos, Casas de Câmbio, Cassinos,
Apostas, Armas e Munições, Artigos de Luxo.
Contribui com **25 pontos** no score.

## Níveis de risco

| Score    | Nível    |
|----------|----------|
| 0        | BAIXO    |
| 1 – 35   | MEDIO    |
| 36 – 70  | ALTO     |
| 71 – 100 | CRITICO  |

## Instalação

```bash
cd mcp_antifraude
pip install -r requirements.txt
```

## Execução direta (stdio)

```bash
python server.py
```

## Testes

```bash
python test_server.py
```

## Registro no Bob (mcp.json)

Adicione ao seu `mcp.json` (workspace ou global):

```json
{
  "mcpServers": {
    "anti-fraude": {
      "command": "python",
      "args": ["<caminho absoluto>/mcp_antifraude/server.py"]
    }
  }
}
```

> **Dica:** use `uv run` para ambientes isolados:
> ```json
> {
>   "mcpServers": {
>     "anti-fraude": {
>       "command": "uv",
>       "args": ["run", "--with", "mcp[cli]", "python", "<caminho>/server.py"]
>     }
>   }
> }
> ```

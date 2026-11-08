# Como funciona a detecção por GPS no sistema

## Visão geral

Quando o agente recebe uma nova transação, ele verifica se a localização
informada é fisicamente compatível com o histórico recente do associado.
A lógica é simples: se alguém comprou em Porto Alegre há 12 minutos, é
impossível estar fazendo uma compra em Tóquio agora.

Essa verificação é feita pela função `_regra_velocidade_impossivel` no
arquivo `mcp_antifraude/server.py`.

---

## Passo 1 — Calcular a distância real entre dois pontos

O sistema usa a **fórmula de Haversine**, que calcula a distância em linha reta
(km) entre dois pontos no globo terrestre usando latitude e longitude.

```
distância_km = haversine(lat_anterior, lon_anterior, lat_atual, lon_atual)
```

Exemplo: Porto Alegre (RS) → Tóquio (JP) = **18.822 km**

---

## Passo 2 — Calcular a velocidade implícita

Com a distância e o tempo entre as duas transações, o sistema calcula a
velocidade que o associado teria que ter se deslocado:

```
velocidade_kmh = distância_km / (minutos_entre_transações / 60)
```

Exemplo: 18.822 km em 12 minutos = **94.115 km/h**

---

## Passo 3 — Classificar o nível de anomalia

O sistema compara essa velocidade com três limiares fixos definidos no código:

| Velocidade implícita     | Nível      | Sub-score GPS |
|--------------------------|------------|---------------|
| > 600 km/h               | CRÍTICO    | +45 pontos    |
| > 200 km/h               | SUSPEITO   | +35 pontos    |
| > 80 km/h                | ALERTA     | +20 pontos    |
| Mudança de estado < 60min + distância > 100 km | SUSPEITO | +35 pontos |
| Mudança de estado < 30min (qualquer velocidade) | ALERTA   | +20 pontos    |

O limiar de 600 km/h cobre qualquer transporte terrestre e a maioria dos voos
domésticos de curta distância. Acima disso, não existe explicação plausível
além de um cartão sendo usado em dois lugares ao mesmo tempo.

A janela de tempo verificada é de **120 minutos** — qualquer transação anterior
dentro desse intervalo é comparada contra a transação atual. O sistema guarda
o **pior caso** encontrado (maior score) dentro da janela.

---

## Passo 4 — Identificar o estado via centróide

Se a transação não tiver o campo `estado` preenchido, o sistema deduz o estado
pelo centróide mais próximo entre os 27 estados brasileiros cadastrados. Isso
permite detectar mudanças interestaduais mesmo quando o campo `estado` não
está no payload:

```python
def _estado_da_coordenada(lat, lon):
    # Calcula haversine contra cada capital/centróide
    # Retorna a sigla do estado mais próximo
```

---

## Passo 5 — Como o score GPS entra no score final

O sub-score GPS é somado diretamente ao score total da transação, que é
limitado a 100 pontos:

```
score_final = score_gps + score_pico_transacao + score_perfil_incomum
score_final = min(score_final, 100)
```

Com score_gps = 45 (nível crítico) + score_pico = 35 + score_perfil = 25,
o resultado seria 105 → limitado a **100/100**.

---

## Passo 6 — Como o histórico é salvo

Após cada análise, a transação atual é **adicionada ao histórico** do associado
em memória (`_HISTORICO`), dentro do servidor MCP:

```python
_HISTORICO.setdefault(assoc_id, []).append(transacao)
```

Isso significa que, na mesma sessão, transações consecutivas do mesmo
associado formam um histórico crescente. A próxima análise já vai comparar
contra todas as anteriores, inclusive a que acabou de ser analisada.

No Streamlit, o histórico da sessão é persistido em `st.session_state.historico_mcp`
e re-injetado em `mcp_server._HISTORICO` antes de cada análise, garantindo
continuidade mesmo entre reruns da interface.

---

## Exemplo completo: RS → Tóquio

```
Transação anterior:
  cidade: Porto Alegre | estado: RS
  lat: -30.03 | lon: -51.21
  timestamp: 2026-11-08T01:00:00

Transação atual:
  cidade: Tóquio | lat: 35.67 | lon: 139.65
  timestamp: 2026-11-08T01:12:00

Cálculo:
  distância = haversine(-30.03, -51.21, 35.67, 139.65) = 18.822 km
  diff_min  = 12 minutos
  velocidade = 18.822 / (12/60) = 94.115 km/h

  → velocidade > 600 km/h → nível CRÍTICO → score_gps = 45
  → pior caso encontrado: detalhe registrado com distância, velocidade e IDs

Score final: 45 (GPS) + 35 (pico) + 25 (perfil) = 105 → cap → 100
Nível: CRÍTICO → decisão: BLOQUEADA → HITL ativado
```

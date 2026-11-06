"""
Testes manuais das ferramentas analisar_risco_transacao e explicar_risco_fraude.
Execute: python test_server.py
"""
import json
import sys
import os

# Garante que o módulo server.py seja encontrado
sys.path.insert(0, os.path.dirname(__file__))

from server import analisar_risco_transacao, explicar_risco_fraude  # type: ignore

SEP = "-" * 60


def _rodar(titulo: str, payload: dict) -> None:
    print(f"\n{SEP}")
    print(f"  {titulo}")
    print(SEP)
    resultado = analisar_risco_transacao(json.dumps(payload))
    print(json.dumps(json.loads(resultado), indent=2, ensure_ascii=False))


# ── Caso 1: Transação normal, sem alertas ──────────────────────────────────
_rodar(
    "CASO 1 — Transação normal (espera score=0)",
    {
        "transacao_id": "tnova_01",
        "associado_id": "assoc_001",
        "valor": 130.00,               # dentro da média (~129 R$)
        "categoria": "Supermercados",
        "timestamp": "2026-11-02T14:00:00",
        "latitude": -23.5505,
        "longitude": -46.6333,
    },
)

# ── Caso 2: Pico de Transação ──────────────────────────────────────────────
_rodar(
    "CASO 2 — Pico de Transação (valor 3x+ acima da média)",
    {
        "transacao_id": "tnova_02",
        "associado_id": "assoc_001",
        "valor": 1500.00,              # média ~129 R$, 1500 = ~11.6x
        "categoria": "Supermercados",
        "timestamp": "2026-11-02T10:00:00",
        "latitude": -23.5505,
        "longitude": -46.6333,
    },
)

# ── Caso 3: Perfil Incomum (Joalheria às 02h) ──────────────────────────────
_rodar(
    "CASO 3 — Perfil Incomum (Joalheria de madrugada)",
    {
        "transacao_id": "tnova_03",
        "associado_id": "assoc_002",
        "valor": 300.00,
        "categoria": "Joalherias",
        "timestamp": "2026-11-03T02:30:00",
        "latitude": -22.9068,
        "longitude": -43.1729,
    },
)

# ── Caso 4: Velocidade Impossível (São Paulo → Rio em 20 min) ─────────────
_rodar(
    "CASO 4 — Velocidade Impossível (SP → RJ em 20 min)",
    {
        "transacao_id": "tnova_04",
        "associado_id": "assoc_001",
        # Última transação do assoc_001 está em SP (-23.55, -46.63) às 10:30
        # Esta chega no Rio de Janeiro às 10:50 — 20 min, ~360 km → ~1.080 km/h
        "valor": 90.00,
        "categoria": "Restaurantes",
        "timestamp": "2026-11-02T10:50:00",
        "latitude": -22.9068,          # Rio de Janeiro
        "longitude": -43.1729,
    },
)

# ── Caso 5: Todas as três regras violadas ─────────────────────────────────
_rodar(
    "CASO 5 — Score máximo: Velocidade Impossível + Pico + Perfil Incomum",
    {
        "transacao_id": "tnova_05",
        "associado_id": "assoc_001",
        # velocidade impossível: RJ, 10 min após a transação de SP (10:30)
        # pico: R$5.000 >> média ~129 R$
        # perfil incomum: Eletrônicos às 02h
        "valor": 5000.00,
        "categoria": "Eletrônicos",
        "timestamp": "2026-11-02T02:40:00",
        "latitude": -22.9068,
        "longitude": -43.1729,
    },
)

# ── Casos de teste: explicar_risco_fraude ─────────────────────────────────

def _rodar_explicacao(titulo: str, resultado_analise: str) -> None:
    print(f"\n{SEP}")
    print(f"  {titulo}")
    print(SEP)
    explicacao = explicar_risco_fraude(resultado_analise)
    dados = json.loads(explicacao)
    print(f"  score_risco          : {dados.get('score_risco')}")
    print(f"  requer_validacao     : {dados.get('requer_validacao')}")
    print(f"  alerta_falso_positivo: {dados.get('alerta_falso_positivo')}")
    print(f"  titulo               : {dados.get('titulo')}")
    print(f"\n  --- mensagem_associado ---")
    print(dados.get("mensagem_associado", ""))
    print(f"\n  --- orientacao ---")
    print(dados.get("orientacao", ""))


# Prepara os resultados de análise que serviram de base para os testes anteriores

_resultado_caso1 = analisar_risco_transacao(json.dumps({
    "transacao_id": "tnova_01", "associado_id": "assoc_001",
    "valor": 130.00, "categoria": "Supermercados",
    "timestamp": "2026-11-02T14:00:00",
    "latitude": -23.5505, "longitude": -46.6333,
}))

_resultado_caso2 = analisar_risco_transacao(json.dumps({
    "transacao_id": "tnova_02b", "associado_id": "assoc_001",
    "valor": 1500.00, "categoria": "Supermercados",
    "timestamp": "2026-11-02T10:00:00",
    "latitude": -23.5505, "longitude": -46.6333,
}))

_resultado_caso3 = analisar_risco_transacao(json.dumps({
    "transacao_id": "tnova_03b", "associado_id": "assoc_002",
    "valor": 300.00, "categoria": "Joalherias",
    "timestamp": "2026-11-03T02:30:00",
    "latitude": -22.9068, "longitude": -43.1729,
}))

_resultado_caso5 = analisar_risco_transacao(json.dumps({
    "transacao_id": "tnova_05b", "associado_id": "assoc_001",
    "valor": 5000.00, "categoria": "Eletrônicos",
    "timestamp": "2026-11-02T02:40:00",
    "latitude": -22.9068, "longitude": -43.1729,
}))

# ── Explicação E1: score = 0 → aprovado sem qualquer alerta ──────────────
_rodar_explicacao(
    "EXPLICAÇÃO E1 — Score 0 (normal): alerta_falso_positivo=False, tudo certo",
    _resultado_caso1,
)

# ── Explicação E2: score 35 (só PICO) → falso positivo leve ──────────────
_rodar_explicacao(
    "EXPLICAÇÃO E2 — Pico de Transação (score 35, MÉDIO): alerta_falso_positivo=True, grau leve",
    _resultado_caso2,
)

# ── Explicação E3: score 25 (só PERFIL_INCOMUM) → falso positivo leve ─────
_rodar_explicacao(
    "EXPLICAÇÃO E3 — Perfil Incomum (score 25, MÉDIO): alerta_falso_positivo=True, grau leve",
    _resultado_caso3,
)

# ── Explicação E4: score 60 (PICO + PERFIL) → falso positivo moderado ─────
_resultado_pico_perfil = analisar_risco_transacao(json.dumps({
    "transacao_id": "tnova_06",
    "associado_id": "assoc_002",
    "valor": 5000.00,           # pico para assoc_002 (média ~423 R$) → score +35
    "categoria": "Joalherias",  # alto risco às 03h → score +25  total: 60
    "timestamp": "2026-11-03T03:00:00",
    "latitude": -22.9068,
    "longitude": -43.1729,
}))
_rodar_explicacao(
    "EXPLICAÇÃO E5 — Pico + Perfil Incomum (score 60, ALTO): alerta_falso_positivo=True, grau moderado",
    _resultado_pico_perfil,
)

# ── Explicação E5: score > 70 → bloqueio real, sem falso positivo ─────────
_rodar_explicacao(
    "EXPLICAÇÃO E6 — Score máximo (100, CRÍTICO): alerta_falso_positivo=False, requer validação",
    _resultado_caso5,
)

# ── Assertions automáticas ────────────────────────────────────────────────
print(f"\n{SEP}")
print("  Verificações automáticas")
print(SEP)

def _assert(condicao: bool, descricao: str) -> None:
    simbolo = "✅" if condicao else "❌"
    print(f"  {simbolo} {descricao}")
    if not condicao:
        raise AssertionError(descricao)

# E1: score 0 → sem alerta de falso positivo
e1 = json.loads(explicar_risco_fraude(_resultado_caso1))
_assert(e1["alerta_falso_positivo"] is False, "E1: score=0 → alerta_falso_positivo deve ser False")
_assert(e1["requer_validacao"] is False,      "E1: score=0 → requer_validacao deve ser False")

# E2: score 35 (só pico) → alerta de falso positivo, sem bloqueio
e2 = json.loads(explicar_risco_fraude(_resultado_caso2))
_assert(e2["alerta_falso_positivo"] is True,  "E2: score=35 → alerta_falso_positivo deve ser True")
_assert(e2["requer_validacao"] is False,      "E2: score=35 → requer_validacao deve ser False")
_assert("falso positivo" in e2["mensagem_associado"], "E2: mensagem deve mencionar 'falso positivo'")
_assert("leve" in e2["mensagem_associado"],           "E2: grau deve ser 'leve' para score ≤ 35")

# E3: score 25 (perfil incomum) → alerta de falso positivo
e3 = json.loads(explicar_risco_fraude(_resultado_caso3))
_assert(e3["alerta_falso_positivo"] is True,  "E3: score=25 → alerta_falso_positivo deve ser True")
_assert("falso positivo" in e3["mensagem_associado"], "E3: mensagem deve mencionar 'falso positivo'")

# E4: score 60 (pico + perfil) → alerta moderado
e4 = json.loads(explicar_risco_fraude(_resultado_pico_perfil))
_assert(e4["alerta_falso_positivo"] is True,  "E4: score=60 → alerta_falso_positivo deve ser True")
_assert("moderado" in e4["mensagem_associado"],       "E4: grau deve ser 'moderado' para score > 35")
_assert("2 sinais" in e4["titulo"],                   "E4: título deve indicar 2 sinais detectados")

# E6: score 100 → bloqueio real, sem falso positivo
e6 = json.loads(explicar_risco_fraude(_resultado_caso5))
_assert(e6["alerta_falso_positivo"] is False, "E6: score=100 → alerta_falso_positivo deve ser False")
_assert(e6["requer_validacao"] is True,       "E6: score=100 → requer_validacao deve ser True")

print(f"\n{SEP}")
print("  Todos os testes concluídos.")
print(SEP)

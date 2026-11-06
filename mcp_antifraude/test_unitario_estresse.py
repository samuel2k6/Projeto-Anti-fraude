"""
Testes Unitários e de Estresse — analisar_risco_transacao
==========================================================
Valida o servidor MCP criado no Dia 2 com três baterias de testes:

  1. INTEGRAÇÃO  — injeta as 15 transações reais de transactions.json e verifica
                   que o servidor retorna resposta estruturada e sem erros.
  2. LATÊNCIA    — mede o tempo de cada análise e garante que fique abaixo de 50 ms.
  3. EDGE CASES  — campos nulos, IDs inexistentes, GPS inválido, JSON malformado,
                   timestamps inválidos, valores negativos e outros casos extremos.

Execução:
    python test_unitario_estresse.py
    python test_unitario_estresse.py --verbose   (mostra retorno completo)
    python test_unitario_estresse.py --stress 500  (repete estresse N vezes)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Importa o módulo do servidor diretamente (sem precisar do runtime MCP)
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))
from server import analisar_risco_transacao  # type: ignore

# ---------------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------------
LATENCIA_MAX_MS = 50.0          # SLA: cada análise deve concluir em até 50 ms
TRANSACTIONS_JSON = Path(__file__).parent.parent / "transactions.json"

# Cores ANSI para output legível
VERDE  = "\033[92m"
AMARELO = "\033[93m"
VERMELHO = "\033[91m"
AZUL   = "\033[94m"
CINZA  = "\033[90m"
RESET  = "\033[0m"
NEGRITO = "\033[1m"


# ---------------------------------------------------------------------------
# Estruturas de resultado
# ---------------------------------------------------------------------------

@dataclass
class ResultadoTeste:
    nome: str
    passou: bool
    latencia_ms: float
    mensagem: str = ""
    retorno: dict[str, Any] = field(default_factory=dict)


@dataclass
class SuiteResultado:
    nome: str
    testes: list[ResultadoTeste] = field(default_factory=list)

    @property
    def passou(self) -> bool:
        return all(t.passou for t in self.testes)

    @property
    def total(self) -> int:
        return len(self.testes)

    @property
    def aprovados(self) -> int:
        return sum(1 for t in self.testes if t.passou)

    @property
    def falhos(self) -> int:
        return self.total - self.aprovados

    @property
    def latencias(self) -> list[float]:
        return [t.latencia_ms for t in self.testes]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chamar(payload: dict[str, Any]) -> tuple[dict[str, Any], float]:
    """Chama analisar_risco_transacao e retorna (resultado_dict, latencia_ms)."""
    inicio = time.perf_counter()
    raw = analisar_risco_transacao(json.dumps(payload, ensure_ascii=False))
    fim = time.perf_counter()
    latencia_ms = (fim - inicio) * 1_000
    resultado = json.loads(raw)
    return resultado, latencia_ms


def _normalizar_transacao(tx: dict[str, Any]) -> dict[str, Any]:
    """
    Converte do formato transactions.json (localizacao aninhada, campos extras)
    para o formato flat aceito pelo servidor (latitude/longitude na raiz).
    Remove campos que começam com '_' (comentários internos do dataset).
    """
    payload: dict[str, Any] = {}
    for k, v in tx.items():
        if k.startswith("_"):          # ignora _comentario, _tipo_fraude etc.
            continue
        if k == "localizacao" and isinstance(v, dict):
            payload["latitude"]  = v.get("latitude")
            payload["longitude"] = v.get("longitude")
            payload["cidade"]    = v.get("cidade", "")
            payload["pais"]      = v.get("pais", "")
        elif k == "score_suspeito_esperado":
            continue                   # metadado de teste, não é campo do servidor
        else:
            payload[k] = v
    return payload


def _ok(nome: str, latencia_ms: float, retorno: dict) -> ResultadoTeste:
    return ResultadoTeste(nome=nome, passou=True,
                          latencia_ms=latencia_ms, retorno=retorno)


def _falha(nome: str, latencia_ms: float, msg: str, retorno: dict = {}) -> ResultadoTeste:
    return ResultadoTeste(nome=nome, passou=False,
                          latencia_ms=latencia_ms, mensagem=msg, retorno=retorno)


def _imprimir_linha(resultado: ResultadoTeste, verbose: bool) -> None:
    icone = f"{VERDE}✔{RESET}" if resultado.passou else f"{VERMELHO}✘{RESET}"
    lat_cor = VERDE if resultado.latencia_ms <= LATENCIA_MAX_MS else AMARELO
    lat_str = f"{lat_cor}{resultado.latencia_ms:6.2f} ms{RESET}"
    msg = f"  {CINZA}{resultado.mensagem}{RESET}" if resultado.mensagem and not resultado.passou else ""
    print(f"  {icone}  {lat_str}  {resultado.nome}{msg}")
    if verbose and resultado.retorno:
        print(f"{CINZA}{json.dumps(resultado.retorno, ensure_ascii=False, indent=4)}{RESET}")


# ===========================================================================
# SUITE 1 — Integração com as 15 transações reais
# ===========================================================================

def suite_integracao(verbose: bool = False) -> SuiteResultado:
    suite = SuiteResultado("INTEGRAÇÃO — 15 transações do transactions.json")

    if not TRANSACTIONS_JSON.exists():
        t = _falha("carregar transactions.json", 0.0,
                   f"Arquivo não encontrado: {TRANSACTIONS_JSON}")
        suite.testes.append(t)
        return suite

    with TRANSACTIONS_JSON.open(encoding="utf-8") as f:
        dataset = json.load(f)

    transacoes = dataset.get("transacoes", [])

    for tx_raw in transacoes:
        tx_id   = tx_raw.get("transacao_id", "sem-id")
        comentario = tx_raw.get("_comentario", "")
        nome_teste = f"{tx_id}  {CINZA}{comentario[:60]}{RESET}"

        payload = _normalizar_transacao(tx_raw)

        try:
            resultado, lat = _chamar(payload)
        except Exception as exc:
            suite.testes.append(_falha(nome_teste, 0.0, f"Exceção não tratada: {exc}"))
            continue

        # Verificações estruturais do retorno
        if "erro" in resultado:
            suite.testes.append(_falha(nome_teste, lat,
                f"Servidor retornou erro: {resultado['erro']}", resultado))
            continue

        campos_esperados = ["transacao_id", "associado_id", "score_risco",
                            "nivel_risco", "regras_violadas", "historico_usado"]
        ausentes = [c for c in campos_esperados if c not in resultado]
        if ausentes:
            suite.testes.append(_falha(nome_teste, lat,
                f"Campos ausentes na resposta: {ausentes}", resultado))
            continue

        score = resultado["score_risco"]
        if not (0 <= score <= 100):
            suite.testes.append(_falha(nome_teste, lat,
                f"score_risco fora do intervalo 0-100: {score}", resultado))
            continue

        if resultado["nivel_risco"] not in {"BAIXO", "MEDIO", "ALTO", "CRITICO"}:
            suite.testes.append(_falha(nome_teste, lat,
                f"nivel_risco inválido: {resultado['nivel_risco']}", resultado))
            continue

        suite.testes.append(_ok(nome_teste, lat, resultado))

    return suite


# ===========================================================================
# SUITE 2 — Latência (SLA ≤ 50 ms por transação)
# ===========================================================================

def suite_latencia(n_repeticoes: int = 100, verbose: bool = False) -> SuiteResultado:
    """
    Repete a análise de uma transação padrão N vezes e verifica que
    nenhuma execução ultrapassa LATENCIA_MAX_MS.
    Também mede p50, p95 e p99.
    """
    suite = SuiteResultado(f"LATÊNCIA — {n_repeticoes} repetições (SLA ≤ {LATENCIA_MAX_MS} ms)")

    payload_base = {
        "transacao_id": "stress-lat-001",
        "associado_id": "assoc_001",
        "valor": 1500.00,
        "categoria": "Eletrônicos",
        "timestamp": "2026-11-02T03:00:00",
        "latitude": -23.5505,
        "longitude": -46.6333,
    }

    latencias: list[float] = []

    for i in range(n_repeticoes):
        payload = {**payload_base, "transacao_id": f"stress-lat-{i:04d}"}
        try:
            resultado, lat = _chamar(payload)
            latencias.append(lat)
            passou = lat <= LATENCIA_MAX_MS and "erro" not in resultado
            t = ResultadoTeste(
                nome=f"Iteração {i+1:>4}/{n_repeticoes}  ({lat:.2f} ms)",
                passou=passou,
                latencia_ms=lat,
                mensagem="" if passou else f"Latência acima do SLA ({lat:.2f} ms > {LATENCIA_MAX_MS} ms)",
                retorno=resultado if verbose else {},
            )
        except Exception as exc:
            t = _falha(f"Iteração {i+1:>4}/{n_repeticoes}", 0.0,
                       f"Exceção: {exc}")
        suite.testes.append(t)

    # Adiciona teste de resumo estatístico (não conta como falha, só informa)
    if latencias:
        latencias_sorted = sorted(latencias)
        n = len(latencias_sorted)
        p50 = latencias_sorted[int(n * 0.50) - 1]
        p95 = latencias_sorted[int(n * 0.95) - 1]
        p99 = latencias_sorted[min(int(n * 0.99), n - 1)]
        media = statistics.mean(latencias)
        desvio = statistics.stdev(latencias) if n > 1 else 0.0

        suite._estatisticas = {  # type: ignore[attr-defined]
            "media_ms": round(media, 3),
            "desvio_padrao_ms": round(desvio, 3),
            "p50_ms": round(p50, 3),
            "p95_ms": round(p95, 3),
            "p99_ms": round(p99, 3),
            "max_ms": round(max(latencias), 3),
            "min_ms": round(min(latencias), 3),
            "acima_do_sla": sum(1 for l in latencias if l > LATENCIA_MAX_MS),
        }

    return suite


# ===========================================================================
# SUITE 3 — Edge cases
# ===========================================================================

def suite_edge_cases(verbose: bool = False) -> SuiteResultado:
    suite = SuiteResultado("EDGE CASES — campos nulos, IDs inválidos, GPS corrompido")

    casos: list[tuple[str, dict | str, str | None]] = [
        # (nome, payload_ou_str_bruta, campo_erro_esperado_ou_None)

        # ── Campos obrigatórios ausentes ──────────────────────────────────
        ("Campo 'transacao_id' ausente",
         {"associado_id": "x", "valor": 10.0, "categoria": "Supermercado",
          "timestamp": "2026-11-01T10:00:00"},
         "erro"),

        ("Campo 'associado_id' ausente",
         {"transacao_id": "t-ec1", "valor": 10.0, "categoria": "Supermercado",
          "timestamp": "2026-11-01T10:00:00"},
         "erro"),

        ("Campo 'valor' ausente",
         {"transacao_id": "t-ec2", "associado_id": "assoc_001",
          "categoria": "Supermercado", "timestamp": "2026-11-01T10:00:00"},
         "erro"),

        ("Campo 'categoria' ausente",
         {"transacao_id": "t-ec3", "associado_id": "assoc_001",
          "valor": 100.0, "timestamp": "2026-11-01T10:00:00"},
         "erro"),

        ("Campo 'timestamp' ausente",
         {"transacao_id": "t-ec4", "associado_id": "assoc_001",
          "valor": 100.0, "categoria": "Supermercado"},
         "erro"),

        ("Todos os campos obrigatórios ausentes",
         {},
         "erro"),

        # ── Campos nulos (None → JSON null) ───────────────────────────────
        ("Campo 'valor' nulo (null)",
         {"transacao_id": "t-ec5", "associado_id": "assoc_001",
          "valor": None, "categoria": "Supermercado",
          "timestamp": "2026-11-01T10:00:00"},
         "erro"),  # servidor valida nulos e retorna erro estruturado

        ("Campo 'categoria' nulo (null)",
         {"transacao_id": "t-ec6", "associado_id": "assoc_001",
          "valor": 100.0, "categoria": None,
          "timestamp": "2026-11-01T10:00:00"},
         "erro"),

        ("Campo 'timestamp' nulo (null)",
         {"transacao_id": "t-ec7", "associado_id": "assoc_001",
          "valor": 100.0, "categoria": "Supermercado",
          "timestamp": None},
         "erro"),

        # ── Associado inexistente no histórico ────────────────────────────
        ("associado_id inexistente — sem histórico",
         {"transacao_id": "t-ec8", "associado_id": "ASSOC-INEXISTENTE-999",
          "valor": 100.0, "categoria": "Supermercado",
          "timestamp": "2026-11-01T10:00:00"},
         None),  # deve retornar score=0 sem erro

        ("associado_id string vazia",
         {"transacao_id": "t-ec9", "associado_id": "",
          "valor": 100.0, "categoria": "Supermercado",
          "timestamp": "2026-11-01T10:00:00"},
         None),

        # ── GPS inválido ───────────────────────────────────────────────────
        ("latitude fora do range válido (+95)",
         {"transacao_id": "t-ec10", "associado_id": "assoc_001",
          "valor": 100.0, "categoria": "Supermercado",
          "timestamp": "2026-11-01T10:00:00",
          "latitude": 95.0, "longitude": -46.63},
         None),

        ("longitude fora do range válido (-200)",
         {"transacao_id": "t-ec11", "associado_id": "assoc_001",
          "valor": 100.0, "categoria": "Supermercado",
          "timestamp": "2026-11-01T10:00:00",
          "latitude": -23.55, "longitude": -200.0},
         None),

        ("latitude e longitude como string (tipo errado)",
         {"transacao_id": "t-ec12", "associado_id": "assoc_001",
          "valor": 100.0, "categoria": "Supermercado",
          "timestamp": "2026-11-01T10:00:00",
          "latitude": "invalida", "longitude": "invalida"},
         None),

        ("latitude None, longitude presente",
         {"transacao_id": "t-ec13", "associado_id": "assoc_001",
          "valor": 100.0, "categoria": "Supermercado",
          "timestamp": "2026-11-01T10:00:00",
          "latitude": None, "longitude": -46.63},
         None),

        # ── Timestamp inválido ─────────────────────────────────────────────
        ("timestamp com formato inválido",
         {"transacao_id": "t-ec14", "associado_id": "assoc_001",
          "valor": 100.0, "categoria": "Supermercado",
          "timestamp": "01/11/2026 10:00"},
         "erro"),  # servidor valida formato ISO-8601 e retorna erro estruturado

        ("timestamp com string vazia",
         {"transacao_id": "t-ec15", "associado_id": "assoc_001",
          "valor": 100.0, "categoria": "Supermercado",
          "timestamp": ""},
         "erro"),

        # ── Valores extremos numéricos ─────────────────────────────────────
        ("valor negativo (-999.99)",
         {"transacao_id": "t-ec16", "associado_id": "assoc_001",
          "valor": -999.99, "categoria": "Supermercado",
          "timestamp": "2026-11-01T10:00:00"},
         None),

        ("valor zero (R$ 0,00)",
         {"transacao_id": "t-ec17", "associado_id": "assoc_001",
          "valor": 0.0, "categoria": "Supermercado",
          "timestamp": "2026-11-01T10:00:00"},
         None),

        ("valor absurdamente alto (R$ 999.999.999)",
         {"transacao_id": "t-ec18", "associado_id": "assoc_001",
          "valor": 999_999_999.0, "categoria": "Supermercado",
          "timestamp": "2026-11-01T10:00:00"},
         None),

        # ── JSON malformado ────────────────────────────────────────────────
        ("JSON malformado — string bruta",
         '{"transacao_id": "t-ec19", "associado_id": "assoc_001" INVALIDO}',
         "erro"),

        ("JSON completamente vazio",
         "{}",
         "erro"),

        ("String não-JSON",
         "isso nao e json",
         "erro"),

        ("JSON array em vez de objeto",
         "[1, 2, 3]",
         None),  # comportamento livre — não deve travar

        # ── transacao_id duplicado ─────────────────────────────────────────
        ("transacao_id duplicado — segunda chamada com mesmo ID",
         {"transacao_id": "t-ec20-dup", "associado_id": "assoc_001",
          "valor": 100.0, "categoria": "Supermercado",
          "timestamp": "2026-11-01T10:00:00"},
         None),

        # ── Campos extras desconhecidos ────────────────────────────────────
        ("Campos extras desconhecidos no payload",
         {"transacao_id": "t-ec21", "associado_id": "assoc_001",
          "valor": 100.0, "categoria": "Supermercado",
          "timestamp": "2026-11-01T10:00:00",
          "campo_inventado": "xpto", "outro_campo": 42},
         None),
    ]

    # Primeira passagem de t-ec20 para depois testar o duplicado
    _chamar({
        "transacao_id": "t-ec20-dup",
        "associado_id": "assoc_001",
        "valor": 100.0,
        "categoria": "Supermercado",
        "timestamp": "2026-11-01T09:00:00",
    })

    for nome, payload_ou_str, erro_esperado in casos:
        # Converte dict em JSON string (ou usa string bruta direto)
        if isinstance(payload_ou_str, dict):
            raw_input = json.dumps(payload_ou_str, ensure_ascii=False)
        else:
            raw_input = payload_ou_str  # string já formada (JSON malformado)

        try:
            inicio = time.perf_counter()
            raw_output = analisar_risco_transacao(raw_input)
            lat = (time.perf_counter() - inicio) * 1_000
            resultado = json.loads(raw_output)
        except Exception as exc:
            # Exceção não tratada = falha de estabilidade, sempre reportar
            suite.testes.append(_falha(
                nome, 0.0,
                f"EXCEÇÃO NÃO TRATADA → servidor caiu: {type(exc).__name__}: {exc}"
            ))
            continue

        tem_erro = "erro" in resultado

        if erro_esperado == "erro":
            # Esperamos um retorno de erro estruturado
            if tem_erro:
                suite.testes.append(_ok(nome, lat, resultado))
            else:
                suite.testes.append(_falha(nome, lat,
                    "Esperava campo 'erro' na resposta, mas não veio.", resultado))
        else:
            # Esperamos que o servidor NÃO trave (pode retornar erro ou score)
            # A única falha aceitável é uma exceção não tratada (já capturada acima)
            suite.testes.append(_ok(nome, lat, resultado))

    return suite


# ===========================================================================
# Runner principal
# ===========================================================================

def _imprimir_header(texto: str) -> None:
    print(f"\n{NEGRITO}{AZUL}{'═' * 70}{RESET}")
    print(f"{NEGRITO}{AZUL}  {texto}{RESET}")
    print(f"{NEGRITO}{AZUL}{'═' * 70}{RESET}")


def _imprimir_suite(suite: SuiteResultado, verbose: bool) -> None:
    _imprimir_header(suite.nome)
    for t in suite.testes:
        _imprimir_linha(t, verbose)

    # Estatísticas de latência extras (só na suite de latência)
    stats = getattr(suite, "_estatisticas", None)
    if stats:
        print(f"\n{NEGRITO}  📊 Estatísticas de latência:{RESET}")
        print(f"     Média     : {stats['media_ms']:.3f} ms")
        print(f"     Desvio p. : {stats['desvio_padrao_ms']:.3f} ms")
        print(f"     p50       : {stats['p50_ms']:.3f} ms")
        print(f"     p95       : {stats['p95_ms']:.3f} ms")
        print(f"     p99       : {stats['p99_ms']:.3f} ms")
        print(f"     Máx       : {stats['max_ms']:.3f} ms")
        print(f"     Mín       : {stats['min_ms']:.3f} ms")
        cor_sla = VERDE if stats["acima_do_sla"] == 0 else AMARELO
        print(f"     Acima SLA : {cor_sla}{stats['acima_do_sla']}{RESET} de {len(suite.latencias)} execuções")

    status_cor = VERDE if suite.passou else VERMELHO
    status_txt = "PASSOU" if suite.passou else "FALHOU"
    print(f"\n  {status_cor}{NEGRITO}{status_txt}{RESET}  "
          f"({suite.aprovados}/{suite.total} testes aprovados"
          + (f", {suite.falhos} falhos" if suite.falhos else "")
          + ")")


def _imprimir_resumo(suites: list[SuiteResultado]) -> None:
    total_testes  = sum(s.total for s in suites)
    total_passou  = sum(s.aprovados for s in suites)
    total_falhou  = sum(s.falhos for s in suites)
    todas_lat     = [l for s in suites for l in s.latencias]

    print(f"\n{NEGRITO}{'═' * 70}{RESET}")
    print(f"{NEGRITO}  RESUMO GERAL{RESET}")
    print(f"{'═' * 70}")
    print(f"  Testes executados : {total_testes}")
    cor_p = VERDE if total_falhou == 0 else VERMELHO
    print(f"  Aprovados         : {VERDE}{total_passou}{RESET}")
    print(f"  Reprovados        : {cor_p}{total_falhou}{RESET}")
    if todas_lat:
        print(f"  Latência total    : {statistics.mean(todas_lat):.2f} ms (média)")
    print()
    for s in suites:
        icone = f"{VERDE}✔{RESET}" if s.passou else f"{VERMELHO}✘{RESET}"
        print(f"  {icone}  {s.nome}")
    print(f"{'═' * 70}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Testes unitários e de estresse — analisar_risco_transacao"
    )
    parser.add_argument("--verbose", action="store_true",
                        help="Exibe o JSON completo de cada resposta")
    parser.add_argument("--stress", type=int, default=100, metavar="N",
                        help="Número de repetições no teste de latência (padrão: 100)")
    args = parser.parse_args()

    print(f"\n{NEGRITO}🛡️  Testes — MCP Anti-Fraude | analisar_risco_transacao{RESET}")
    print(f"{CINZA}   SLA de latência: ≤ {LATENCIA_MAX_MS} ms por transação{RESET}")

    suites = [
        suite_integracao(verbose=args.verbose),
        suite_latencia(n_repeticoes=args.stress, verbose=args.verbose),
        suite_edge_cases(verbose=args.verbose),
    ]

    for s in suites:
        _imprimir_suite(s, verbose=args.verbose)

    _imprimir_resumo(suites)

    # Código de saída não-zero se qualquer teste falhou
    sys.exit(0 if all(s.passou for s in suites) else 1)


if __name__ == "__main__":
    main()

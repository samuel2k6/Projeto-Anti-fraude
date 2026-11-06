# 🛡️ Sistema de Prevenção de Fraudes em Cartões — Sicredi
### AI Experiential Learning Lab | Trilha 4 — Prevenção Inteligente a Fraudes

[![GitHub](https://img.shields.io/badge/GitHub-Repositório-181717?logo=github&logoColor=white)](https://github.com/samuel2k6/Projeto-Anti-fraude)
[![Streamlit](https://img.shields.io/badge/Streamlit-Chat%20Demo-FF4B4B?logo=streamlit&logoColor=white)](https://projeto-anti-fraude-dbxqsevzzagoym2spwhrug.streamlit.app/)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-Model%20Context%20Protocol-0f62fe)](https://modelcontextprotocol.io/)
[![IBM watsonx](https://img.shields.io/badge/IBM-watsonx%20Orchestrate-1F70C1?logo=ibm&logoColor=white)](https://www.ibm.com/products/watsonx-orchestrate)

> **Arquétipos aplicados:**
> - 🔒 **Guardião de Tomada de Decisão** — Avalia se uma transação deve prosseguir com base em múltiplos critérios de risco, pontuação de confiança e explicabilidade.
> - 🧠 **Redutor de Carga Cognitiva** — Sintetiza sinais transacionais complexos em scores e alertas acionáveis, eliminando a necessidade de análise manual exaustiva.

---

## 🚀 Acesso Rápido

| | Link |
|---|---|
| 💬 **Demo ao vivo (Streamlit)** | [samuel2k6-projeto-anti-fraude-streamlit-app-8dpf8y.streamlit.app](https://projeto-anti-fraude-dbxqsevzzagoym2spwhrug.streamlit.app/) |
| 📦 **Repositório GitHub** | [github.com/samuel2k6/Projeto-Anti-fraude](https://github.com/samuel2k6/Projeto-Anti-fraude) |

> **Como fazer o deploy da demo:** veja a seção [8. Instalação e Execução](#8-instalação-e-execução) abaixo, ou acesse o link do Streamlit Cloud diretamente acima.

---

## 📌 Sumário

1. [Escopo Funcional](#1-escopo-funcional)
2. [Requisitos Não-Funcionais](#2-requisitos-não-funcionais)
3. [Tipos de Fraude Detectados](#3-tipos-de-fraude-detectados)
4. [Fluxo de Decisão do Agente](#4-fluxo-de-decisão-do-agente)
5. [Estrutura de Dados](#5-estrutura-de-dados)
6. [Regras de Scoring](#6-regras-de-scoring)
7. [Referências de Arquivos](#7-referências-de-arquivos)

---

## 1. Escopo Funcional

### 1.1 Objetivo Geral
Desenvolver um sistema de IA Agêntica capaz de **detectar, pontuar e intervir em transações suspeitas** de cartões de crédito e débito em tempo real, antes da conclusão financeira, protegendo os associados do Sicredi e reduzindo perdas financeiras.

### 1.2 Módulos Funcionais

#### 🔍 F1 — Motor de Ingestão e Normalização
- Recebe eventos de transação via stream (Kafka / API REST)
- Normaliza campos: valor, categoria, coordenadas GPS, timestamp ISO 8601
- Enriquece com histórico do associado (últimas 30 transações)
- **Latência de ingestão:** ≤ 50 ms

#### 🤖 F2 — Agente de Avaliação de Risco (Guardião)
- Avalia cada transação contra **múltiplos critérios de risco simultâneos**:
  - Padrão histórico do associado (categoria, valor médio, localização habitual)
  - Velocidade de transações (frequência no intervalo de tempo)
  - Coerência geográfica (viagem impossível por GPS)
  - Listas negras de estabelecimentos e BINs
  - Horário atípico vs. perfil de consumo
- Gera um `score_suspeito` de 0.0 a 1.0 com explicação dos fatores
- **Latência de scoring:** ≤ 200 ms (p99)

#### 🚦 F3 — Motor de Decisão e Intervenção
| Score | Ação | Responsável |
|-------|------|-------------|
| 0.0 – 0.39 | ✅ Aprovar automaticamente | Sistema |
| 0.40 – 0.69 | ⚠️ Aprovar + gerar alerta silencioso | Sistema + Analista |
| 0.70 – 0.84 | 🔔 Solicitar confirmação ao associado (push/SMS) | Sistema + Associado |
| 0.85 – 1.0 | 🚫 Bloquear + acionar canal de atendimento | Sistema + Analista Sênior |

#### 📲 F4 — Alerta Preventivo ao Associado (Redutor de Carga)
- Notificação push com linguagem clara e não-técnica
- Exemplo: *"Identificamos uma compra de R$ 2.400 em São Paulo. Você está em Porto Alegre. Foi você? [SIM] [NÃO, BLOQUEAR]"*
- Resposta do associado realimenta o modelo (feedback loop)
- Timeout de 2 minutos para resposta; sem resposta → escala para analista

#### 📊 F5 — Painel de Investigação (Redutor de Carga para Analistas)
- Visão consolidada das transações bloqueadas com:
  - Score e fatores explicativos (SHAP-like)
  - Mapa de localização da transação vs. última localização do associado
  - Histórico de comportamento do associado
  - Linha do tempo de eventos suspeitos
- Priorização automática por severidade e valor em risco

#### 🔄 F6 — Aprendizado Contínuo
- Feedback de confirmações/negações dos associados alimenta o modelo
- Retraining semanal com janela deslizante de 90 dias
- Monitoramento de drift de distribuição (PSI — Population Stability Index)

### 1.3 Integrações Necessárias
| Sistema | Protocolo | Dados Trocados |
|---------|-----------|----------------|
| Processadora de cartões | Kafka / Webhook | Evento de transação em tempo real |
| Core bancário Sicredi | REST API | Histórico transacional do associado |
| Gateway de notificações | REST API | Push, SMS, WhatsApp |
| CRM / Canal de atendimento | Event | Abertura automática de caso |
| Data Lake | Batch | Logs, modelos, dados de treino |

---

## 2. Requisitos Não-Funcionais

### 2.1 Desempenho e Latência

| Requisito | Meta | Crítico |
|-----------|------|---------|
| Latência fim-a-fim (ingestão → decisão) | ≤ 300 ms (p95) | ≤ 500 ms (p99) |
| Latência do motor de scoring | ≤ 200 ms (p99) | ≤ 350 ms |
| Throughput | ≥ 10.000 TPS | ≥ 5.000 TPS degradado |
| Disponibilidade do serviço de decisão | 99,99% (≤ 52 min/ano) | 99,95% |
| Tempo de recuperação após falha (RTO) | ≤ 30 segundos | ≤ 2 minutos |
| RPO (Recovery Point Objective) | ≤ 5 segundos | ≤ 30 segundos |

### 2.2 Precisão do Modelo

| Métrica | Meta mínima |
|---------|-------------|
| Precisão (Precision) em score ≥ 0.85 | ≥ 92% |
| Recall (detecção de fraudes reais) | ≥ 88% |
| Taxa de Falso Positivo (FPR) | ≤ 0,5% |
| F1-Score balanceado | ≥ 0,90 |
| AUC-ROC | ≥ 0,97 |

### 2.3 Segurança e Conformidade

- **LGPD:** Dados pessoais pseudonimizados; logs de decisão auditáveis por 5 anos
- **PCI-DSS Nível 1:** Dados de cartão nunca trafegam em texto plano; tokenização obrigatória
- **Criptografia:** TLS 1.3 em trânsito; AES-256 em repouso
- **Controle de acesso:** RBAC com MFA para acesso ao painel de analistas
- **Explainability:** Toda decisão de bloqueio deve ter registro auditável dos fatores de risco

### 2.4 Escalabilidade e Resiliência

- Arquitetura de microsserviços com auto-scaling horizontal
- Circuit breaker em todas as chamadas de serviços externos
- Modo degradado: se o modelo ML falhar, fallback para regras determinísticas
- Testes de carga com picos de 3x a demanda média (ex: Black Friday, Natal)

### 2.5 Observabilidade

- Rastreamento distribuído (OpenTelemetry)
- Métricas em tempo real: taxa de bloqueios, falsos positivos, latência por percentil
- Alertas automáticos: se FPR > 1% ou latência p99 > 500 ms → PagerDuty

---

## 3. Tipos de Fraude Detectados

| Código | Tipo | Sinal Detectado |
|--------|------|-----------------|
| F-001 | **Carding / Força Bruta** | ≥ 3 transações de baixo valor (< R$10) em < 5 min no mesmo estabelecimento ou BIN |
| F-002 | **Viagem Impossível (GPS)** | Transação em localização geograficamente impossível dado o tempo desde a última transação |
| F-003 | **Transação Fora do Perfil** | Valor ou categoria com desvio padrão > 3σ do histórico do associado |
| F-004 | **Uso em País de Alto Risco** | Transação em país com índice de fraude > limiar configurável |
| F-005 | **Card Not Present em Novo Dispositivo** | E-commerce em device_id nunca visto + valor alto |
| F-006 | **Horário Atípico** | Transação entre 02h–05h em estabelecimento não habitual |

---

## 4. Fluxo de Decisão do Agente

Veja o arquivo [`architecture.md`](./architecture.md) para o diagrama completo.

**Resumo do fluxo:**
1. Evento de transação chega via stream
2. Agente enriquece com contexto histórico do associado
3. Cada regra de risco produz um sub-score parcial
4. Score final = média ponderada dos sub-scores
5. Motor de decisão aplica thresholds e dispara ação
6. Resultado é registrado e realimenta o modelo

---

## 5. Estrutura de Dados

### Evento de Transação (Entrada)
```json
{
  "associado_id": "string (UUID)",
  "transacao_id": "string (UUID)",
  "valor": "number (BRL, 2 casas decimais)",
  "categoria": "string (MCC code description)",
  "localizacao": {
    "latitude": "number",
    "longitude": "number",
    "cidade": "string",
    "pais": "string (ISO 3166-1 alpha-2)"
  },
  "timestamp": "string (ISO 8601)",
  "score_suspeito_esperado": "number [0.0 – 1.0]"
}
```

### Resposta do Motor de Decisão (Saída)
```json
{
  "transacao_id": "string",
  "decisao": "APROVADA | ALERTA | CONFIRMAR_ASSOCIADO | BLOQUEADA",
  "score_final": "number [0.0 – 1.0]",
  "fatores_risco": ["string"],
  "acao_tomada": "string",
  "timestamp_decisao": "string (ISO 8601)",
  "latencia_ms": "number"
}
```

---

## 6. Regras de Scoring

Veja o arquivo [`fraud_rules.json`](./fraud_rules.json) para as regras completas com pesos.

**Pesos dos fatores de risco (soma = 1.0):**
| Fator | Peso |
|-------|------|
| Velocidade de transações | 0.25 |
| Coerência geográfica (GPS) | 0.30 |
| Desvio do perfil do associado | 0.25 |
| Lista negra de estabelecimento | 0.10 |
| Horário atípico | 0.10 |

---

## 7. Referências de Arquivos

| Arquivo | Descrição |
|---------|-----------|
| [`README.md`](./README.md) | Este documento — escopo e requisitos |
| [`transactions.json`](./transactions.json) | 15 transações fictícias para testes locais |
| [`architecture.md`](./architecture.md) | Diagrama de arquitetura do sistema |
| [`fraud_rules.json`](./fraud_rules.json) | Regras e pesos do motor de scoring |
| [`pyproject.toml`](./pyproject.toml) | Metadados e dependências do projeto (PEP 517) |
| [`requirements.txt`](./requirements.txt) | Dependências para instalação direta via pip |
| [`setup.bat`](./setup.bat) | Instalador automático para Windows |
| [`setup.sh`](./setup.sh) | Instalador automático para Linux / macOS |
| [`orchestration/`](./orchestration/) | Pipeline de orquestração do agente anti-fraude |

---

## 8. Instalação e Execução

### Pré-requisitos

| Software | Versão mínima | Download |
|----------|--------------|----------|
| Python   | 3.11         | https://www.python.org/downloads/ |
| pip      | 23.0         | incluso no Python 3.11+ |

### Instalação automática

**Windows:**
```bat
setup.bat
```

**Linux / macOS:**
```bash
bash setup.sh
```

### Instalação manual

```bash
# 1. Criar e ativar ambiente virtual
python -m venv .venv

# Windows
.venv\Scripts\activate.bat

# Linux / macOS
source .venv/bin/activate

# 2. Instalar dependências
pip install -r requirements.txt
```

### Verificar instalação

```bash
python -c "import mcp; print('mcp SDK v' + mcp.__version__)"
```

### Executar o pipeline de orquestração

```bash
python -m orchestration.pipeline
```

### Executar os testes do servidor MCP

```bash
python mcp_antifraude/test_server.py
```

### Executar todos os testes (Prompts 1 a 7)

```bash
python run_tests.py
```

### 💬 Iniciar a demo de chat (watsonx Orchestrate simulado)

```bash
streamlit run streamlit_app.py
```

O app abrirá automaticamente em `http://localhost:8501`.

**Deploy no Streamlit Community Cloud (link permanente gratuito):**

1. Faça push do repositório para o GitHub
2. Acesse [share.streamlit.io](https://share.streamlit.io) → **"Deploy an app"**
3. Selecione o repositório `samuel2k6/Projeto-Anti-fraude`
4. Arquivo principal: `streamlit_app.py`
5. Clique em **Deploy** — o link público será gerado automaticamente

---

*Projeto desenvolvido no contexto do AI Experiential Learning Lab — IBM SkillsBuild / 2026*
*Trilha 4: Prevenção Inteligente a Fraudes e Segurança do Associado com SICREDI*

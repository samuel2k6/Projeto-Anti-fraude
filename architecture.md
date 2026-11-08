# 🏗️ Arquitetura — Sistema de Prevenção de Fraudes em Tempo Real
### Sicredi | Trilha 4 | AI Experiential Learning Lab 2026

---

## Diagrama de Arquitetura Geral

```mermaid
graph TB
    subgraph ENTRADA["📥 CAMADA DE INGESTÃO"]
        POS["💳 Terminal POS / e-Commerce\n(envia cidade, estado, país,\ndata_hora_local, fuso_horario)"]
        STREAM["⚡ Kafka Event Stream"]
        API_GW["🔌 API Gateway (REST)"]
    end

    subgraph AGENTE["🤖 AGENTE DE DETECÇÃO — Guardião de Tomada de Decisão"]
        direction TB
        NORM["🗺️ Normalizador de Localização\n_nivelar_localizacao()\n(aplana localizacao{} → raiz)"]
        ENRICH["🔎 Enriquecedor de Contexto\n(histórico associado + perfil)"]
        RULES["📏 Motor de Regras\nDeterminísticas (F-001 a F-006)"]
        ML["🧠 Modelo ML\n(Gradient Boosting + Features)"]
        SCORE["🎯 Agregador de Score\n(média ponderada 0.0–1.0)"]
        EXPLAIN["📋 Gerador de Explicação\n(linguagem natural c/ cidade/estado/hora local)"]
        NORM --> ENRICH
        ENRICH --> RULES
        ENRICH --> ML
        RULES --> SCORE
        ML --> SCORE
        SCORE --> EXPLAIN
    end

    subgraph DECISAO["🚦 MOTOR DE DECISÃO"]
        T1["✅ Score 0.0–0.39\nAprovar"]
        T2["⚠️ Score 0.40–0.69\nAlerta Silencioso"]
        T3["🔔 Score 0.70–0.84\nConfirmar c/ Associado"]
        T4["🚫 Score 0.85–1.0\nBloquear"]
    end

    subgraph NOTIF["📲 CAMADA DE NOTIFICAÇÃO — Redutor de Carga Cognitiva"]
        PUSH["📱 Push Notification\n(app Sicredi)"]
        SMS["💬 SMS / WhatsApp"]
        ANALISTA["👨‍💼 Painel do Analista\n(dashboard priorizado)"]
    end

    subgraph DADOS["🗄️ CAMADA DE DADOS"]
        HIST["📊 Banco de Histórico\nTransacional (Redis + PostgreSQL)"]
        BLACKLIST["🚫 Lista Negra\n(BINs, MCC, países)"]
        MODELO["🤖 Model Registry\n(watsonx.ai)"]
        LAKE["🏞️ Data Lake\n(logs + retraining)"]
    end

    subgraph FEEDBACK["🔄 FEEDBACK & APRENDIZADO"]
        RESP["✋ Resposta do Associado\n(confirmou / negou)"]
        DRIFT["📉 Monitor de Drift\n(PSI semanal)"]
        RETRAIN["🔁 Pipeline de Retraining\n(janela 90 dias)"]
    end

    POS --> STREAM
    API_GW --> STREAM
    STREAM --> NORM
    HIST --> ENRICH
    BLACKLIST --> RULES
    MODELO --> ML

    EXPLAIN --> T1
    EXPLAIN --> T2
    EXPLAIN --> T3
    EXPLAIN --> T4

    T1 --> LAKE
    T2 --> ANALISTA
    T3 --> PUSH
    T3 --> SMS
    T4 --> PUSH
    T4 --> ANALISTA

    LAKE --> DRIFT
    RESP --> LAKE
    DRIFT --> RETRAIN
    RETRAIN --> MODELO

    style ENTRADA fill:#e8f4fd,stroke:#3b82d4
    style AGENTE fill:#f0fdf4,stroke:#16a34a
    style DECISAO fill:#fef9c3,stroke:#ca8a04
    style NOTIF fill:#fdf4ff,stroke:#9333ea
    style DADOS fill:#f7f8fa,stroke:#6b7280
    style FEEDBACK fill:#fff1f2,stroke:#e11d48
```

---

## Diagrama de Fluxo de Decisão (por Transação)

```mermaid
sequenceDiagram
    actor Associado as 💳 Associado
    participant POS as Terminal POS
    participant Kafka as ⚡ Kafka
    participant Agente as 🤖 Agente IA
    participant Cache as 🗄️ Cache Redis
    participant Decisao as 🚦 Motor Decisão
    participant Notif as 📲 Notificações
    participant Analista as 👨‍💼 Analista

    Associado->>POS: Inicia transação
    POS->>Kafka: Publica evento (< 10ms)
    Kafka->>Agente: Consome evento
    Agente->>Cache: Busca histórico associado (< 20ms)
    Cache-->>Agente: Perfil + últimas 30 txn

    Note over Agente: Avalia 6 regras de risco em paralelo
    Agente->>Agente: Calcula score_final (0.0–1.0)
    Agente->>Decisao: Envia score + fatores explicativos

    alt Score 0.0–0.39 ✅ Aprovada
        Decisao->>POS: APROVADA (< 300ms total)
        POS-->>Associado: Transação aprovada
    else Score 0.40–0.69 ⚠️ Alerta
        Decisao->>POS: APROVADA
        Decisao->>Analista: Alerta silencioso no painel
        POS-->>Associado: Transação aprovada
    else Score 0.70–0.84 🔔 Confirmação
        Decisao->>POS: PENDENTE (aguarda confirmação)
        Decisao->>Notif: Dispara push + SMS ao associado
        Notif-->>Associado: "Confirma compra de R$X em Y?"
        alt Associado confirma
            Associado->>Decisao: CONFIRMAR
            Decisao->>POS: APROVADA
        else Associado nega ou timeout (2 min)
            Associado->>Decisao: BLOQUEAR / timeout
            Decisao->>POS: BLOQUEADA
            Decisao->>Analista: Abre caso de investigação
        end
    else Score 0.85–1.0 🚫 Bloqueada
        Decisao->>POS: BLOQUEADA (< 300ms total)
        POS-->>Associado: Transação recusada
        Decisao->>Notif: Notifica associado + abre caso
        Decisao->>Analista: Caso prioritário com evidências
    end
```

---

## Diagrama de Componentes e Implantação

```mermaid
graph LR
    subgraph CLOUD["☁️ IBM Cloud / watsonx"]
        subgraph K8S["Kubernetes Cluster"]
            SVC_INGEST["fraud-ingestor\n(Pod × 3)"]
            SVC_SCORE["fraud-scorer\n(Pod × 5)"]
            SVC_DECIDE["fraud-decision\n(Pod × 3)"]
            SVC_NOTIFY["fraud-notifier\n(Pod × 2)"]
            SVC_DASH["fraud-dashboard\n(Pod × 2)"]
        end

        subgraph DATA_PLANE["Data Plane"]
            KAFKA["Apache Kafka\n(3 brokers)"]
            REDIS["Redis Cluster\n(perfis associados)"]
            POSTGRES["PostgreSQL\n(histórico + logs)"]
            WXAI["watsonx.ai\n(model serving)"]
        end
    end

    subgraph SICREDI_ON_PREM["🏦 Sicredi On-Premises"]
        CORE["Core Bancário"]
        CRM["CRM / Atendimento"]
    end

    SVC_INGEST --> KAFKA
    KAFKA --> SVC_SCORE
    SVC_SCORE --> REDIS
    SVC_SCORE --> WXAI
    SVC_SCORE --> SVC_DECIDE
    SVC_DECIDE --> SVC_NOTIFY
    SVC_DECIDE --> SVC_DASH
    SVC_DECIDE --> POSTGRES
    SVC_NOTIFY --> CRM
    CORE --> REDIS

    style CLOUD fill:#dbeafe,stroke:#2563eb
    style SICREDI_ON_PREM fill:#fef3c7,stroke:#d97706
    style K8S fill:#f0fdf4,stroke:#16a34a
    style DATA_PLANE fill:#f5f3ff,stroke:#7c3aed
```

---

## Modelo de Dados — Relacionamento de Entidades

```mermaid
erDiagram
    ASSOCIADO {
        string associado_id PK
        string nome
        string segmento
        float ticket_medio
        float ticket_desvio_padrao
        string[] categorias_frequentes
        string[] cidades_frequentes
        string[] estados_frequentes
        float latitude_habitual
        float longitude_habitual
    }

    TRANSACAO {
        string transacao_id PK
        string associado_id FK
        float valor
        string categoria
        float latitude
        float longitude
        string cidade
        string estado
        string pais
        datetime timestamp
        string data_hora_local
        string fuso_horario
        string localizacao_resumo
        string data_hora_exibicao
        float score_suspeito
        string decisao
        int latencia_ms
    }

    FATOR_RISCO {
        string fator_id PK
        string transacao_id FK
        string codigo_regra
        float sub_score
        float peso
        string descricao_explicativa
    }

    ALERTA {
        string alerta_id PK
        string transacao_id FK
        string tipo_canal
        datetime timestamp_envio
        string resposta_associado
        datetime timestamp_resposta
    }

    CASO_INVESTIGACAO {
        string caso_id PK
        string transacao_id FK
        string analista_responsavel
        string status
        datetime aberto_em
        datetime fechado_em
        string resolucao
    }

    ASSOCIADO ||--o{ TRANSACAO : "realiza"
    TRANSACAO ||--o{ FATOR_RISCO : "possui"
    TRANSACAO ||--o| ALERTA : "gera"
    TRANSACAO ||--o| CASO_INVESTIGACAO : "origina"
```

---

## Fluxo de Dados de Localização

```mermaid
flowchart LR
    subgraph ENTRADA["Entrada da Transação"]
        A1["localizacao{}\n  latitude\n  longitude\n  cidade\n  estado\n  pais"]
        A2["Campos no nível raiz\n  data_hora_local\n  fuso_horario"]
    end

    subgraph NORM["_nivelar_localizacao()"]
        B["Promove cidade, estado, pais,\nlatitude, longitude\npara o nível raiz\n(sem sobrescrever)"]
    end

    subgraph SAIDA["Campos produzidos"]
        C1["localizacao_resumo\n→ 'Porto Alegre, RS, BR'"]
        C2["data_hora_exibicao\n→ '01/11/2026 às 10:15\n   (America/Sao_Paulo)'"]
    end

    subgraph USO["Onde são usados"]
        D1["Detalhe da regra GPS (F-002)\n'… entre txn-001 (Porto Alegre, RS, BR)\ne esta compra (Tóquio, Tóquio-to, JP)'"]
        D2["Mensagem ao associado\n(explicar_risco_fraude)"]
        D3["Payload do push\n(NotificacaoPush.construir)"]
        D4["Painel do analista\n(localizacao_resumo)"]
    end

    A1 --> B
    A2 --> SAIDA
    B --> C1
    B --> C2
    C1 --> D1
    C1 --> D2
    C1 --> D3
    C1 --> D4
    C2 --> D2
    C2 --> D3
```

---

## Decisões de Arquitetura (ADRs)

### ADR-001: Stream-first com Kafka
**Decisão:** Usar Apache Kafka como backbone de eventos em vez de REST síncrono para ingestão.
**Motivo:** Desacopla o processador de cartões do agente de IA, evitando que latência do ML impacte o terminal. O resultado da decisão é enviado de volta assincronamente ao autorizador.

### ADR-002: Modelo ML + Regras Determinísticas em paralelo
**Decisão:** Executar regras determinísticas (velocidade, GPS) e modelo ML em paralelo, agregando scores com pesos.
**Motivo:** Regras oferecem explainability e baixa latência; ML captura padrões complexos não cobertos por regras. O fallback em caso de falha do ML é as regras determinísticas isoladas.

### ADR-003: Cache Redis para perfil do associado
**Decisão:** Manter os últimas 30 transações e o perfil comportamental do associado em Redis.
**Motivo:** Latência de leitura < 5 ms contra > 50 ms no banco relacional. TTL de 24 horas com invalidação via evento de nova transação.

### ADR-004: Timeout de 2 minutos para confirmação do associado
**Decisão:** Se o associado não responder ao push/SMS em 2 minutos, enviar um alerta orientando o associado a entrar em contato com sua agência Sicredi — sem bloqueio automático.
**Motivo:** Evitar bloqueios indevidos por falha de conectividade ou atraso na entrega da notificação, preservando a experiência do associado. A agência realiza a validação presencial e aciona os procedimentos cabíveis.

### ADR-005: Campos de localização e data/hora como opcionais
**Decisão:** `cidade`, `estado`, `pais`, `data_hora_local` e `fuso_horario` são opcionais. Quando ausentes, o motor opera normalmente com coordenadas brutas ou sem contexto geográfico textual.
**Motivo:** Retrocompatibilidade com terminais POS e integrações existentes que não fornecem esses campos. A análise de risco (lat/lon para Haversine) não depende dos campos textuais — eles servem exclusivamente para enriquecer as mensagens ao associado e ao analista.

### ADR-006: Nivelamento automático do sub-objeto `localizacao`
**Decisão:** A função `_nivelar_localizacao()` em [`mcp_antifraude/server.py`](./mcp_antifraude/server.py) e a lógica equivalente em [`notificacao_push.py`](./.bob/orchestration/notificacao_push.py) promovem campos aninhados ao nível raiz sem copiar o objeto inteiro.
**Motivo:** O dataset de testes usa `"localizacao": {…}` aninhado (padrão do projeto), mas a API pública do motor aceita campos no nível raiz. Uma única função de normalização no início do fluxo elimina a necessidade de adaptar cada regra individualmente.

---

*Arquitetura projetada conforme os arquétipos: **Guardião de Tomada de Decisão** e **Redutor de Carga Cognitiva** — AI Experiential Learning Lab 2026*

# ClaimTracker Architecture

## Component Diagram

```mermaid
graph TB
    subgraph "Frontend (Next.js)"
        UI[React Pages]
        API_CLIENT[API Client]
    end

    subgraph "Backend (FastAPI)"
        ROUTER[API Routers]
        AUTH[Auth Service]
        CLAIM_SVC[Claim Service]
        HANDBOOK_SVC[Handbook Service]
        REVIEW_SVC[Review Service]
        ANALYTICS_SVC[Analytics Service]

        subgraph "AI Pipeline"
            OCR[OCR Service]
            EXTRACT[Extraction Service]
            PII[PII Masker]

            subgraph "Validator Chain"
                V1[Completeness]
                V2[Amount Check]
                V3[Consistency]
                V4[Exclusion Check]
                V5[RAG Policy Check]
            end

            DECISION[Decision Service]
        end

        subgraph "Data Layer"
            REPO[Repositories]
            MODELS[SQLAlchemy Models]
        end

        subgraph "AI Infrastructure"
            LLM[LLM Client - Groq]
            RAG[RAG Service]
            FAISS[FAISS Index]
            EMBEDDINGS[Sentence Transformers]
        end
    end

    subgraph "External"
        DB[(PostgreSQL)]
        GROQ_API[Groq API]
        N8N[n8n Automation]
    end

    UI --> API_CLIENT --> ROUTER
    ROUTER --> AUTH
    ROUTER --> CLAIM_SVC
    ROUTER --> HANDBOOK_SVC
    ROUTER --> REVIEW_SVC
    ROUTER --> ANALYTICS_SVC

    CLAIM_SVC --> OCR --> EXTRACT --> PII
    EXTRACT --> LLM
    PII --> LLM
    CLAIM_SVC --> DECISION
    DECISION --> V1 --> V2 --> V3 --> V4 --> V5
    V5 --> RAG --> FAISS
    V5 --> LLM
    RAG --> EMBEDDINGS

    CLAIM_SVC --> REPO --> MODELS --> DB
    HANDBOOK_SVC --> EMBEDDINGS --> FAISS
    LLM --> GROQ_API
    CLAIM_SVC --> N8N
```

## Data Flow (Claim Submission)

```mermaid
sequenceDiagram
    participant U as User
    participant FE as Frontend
    participant API as FastAPI
    participant OCR as OCR Service
    participant LLM as Groq LLM
    participant FAISS as FAISS Index
    participant DB as PostgreSQL
    participant N8N as n8n

    U->>FE: Submit claim form + bill PDF
    FE->>API: POST /claims (multipart)
    API->>DB: Save claim (PENDING)
    API->>FE: 201 Created (claim_id)
    API-->>API: Background Task starts

    Note over API: Pipeline (async)
    API->>OCR: Extract text from bill
    OCR-->>API: Raw text
    API->>LLM: Extract structured fields (masked PII)
    LLM-->>API: JSON {diagnosis, amount, ...}
    API->>DB: Save extracted fields

    Note over API: Validator Chain
    API->>API: 1. Completeness ✓
    API->>API: 2. Amount ≤ bill total ✓
    API->>API: 3. Consistency (fuzzy) ✓
    API->>API: 4. Exclusion check (deterministic) ✓
    API->>FAISS: 5. Retrieve top-k handbook chunks
    FAISS-->>API: Relevant clauses
    API->>LLM: Decision with cited clauses
    LLM-->>API: {outcome, confidence, citations}

    API->>DB: Save decision + audit log
    API->>DB: Update status → ACCEPTED/REJECTED/NEEDS_REVIEW
    API->>N8N: Webhook (claim decided)

    FE->>API: GET /claims/{id} (polling)
    API->>FE: Full claim with decision
    FE->>U: Display result with citations
```

## Design Decisions

| Decision | Why |
|---|---|
| **Chain of Responsibility** for validators | Ordering matters: deterministic checks first, LLM last. Chain stops on first failure → no wasted API calls. |
| **Strategy pattern** for LLM client | Swap Groq ↔ OpenAI ↔ local model without touching any service code. |
| **Repository pattern** | No SQL in services. All queries are testable, mockable, and reusable. |
| **FAISS (not pgvector)** | Simpler deployment (no extension), fast in-memory search, good enough for a single handbook (~100-500 chunks). |
| **Exclusion check before LLM** | LLM hallucinated approvals for excluded conditions. Deterministic rule engine prevents this. |
| **Background task (not Celery)** | FastAPI BackgroundTasks are sufficient for single-server deployment. Celery/SQS would be the next step for scaling. |
| **PII masking** | PHI must not leave the network. Regex masking is the minimum; NER would be the next layer. |
| **Confidence threshold** | Prevents over-reliance on LLM. Low-confidence → human review, always. |
| **Versioned prompts** | File-based, not inline. Changes are tracked in Git. Audit log records which version was used. |
| **SQLite for dev** | Same SQLAlchemy models, zero Docker setup for quick iteration. PostgreSQL for prod. |

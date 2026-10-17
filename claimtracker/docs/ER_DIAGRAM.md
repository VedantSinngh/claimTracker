# ClaimTracker ER Diagram

```mermaid
erDiagram
    USERS {
        uuid id PK
        string email UK
        string hashed_password
        string full_name
        enum role "user | reviewer | admin"
        boolean is_active
        timestamp created_at
        timestamp updated_at
    }

    CLAIMS {
        uuid id PK
        uuid user_id FK
        string patient_name
        string claim_item
        string reason
        string address
        date date_of_treatment
        string medical_facility
        numeric claim_amount
        text description
        enum status "PENDING|PROCESSING|ACCEPTED|REJECTED|NEEDS_REVIEW"
        float confidence_score
        timestamp created_at
        timestamp updated_at
    }

    CLAIM_DOCUMENTS {
        uuid id PK
        uuid claim_id FK
        string file_name
        string file_path
        string mime_type
        text raw_ocr_text
        timestamp uploaded_at
    }

    EXTRACTED_FIELDS {
        uuid id PK
        uuid claim_id FK "UNIQUE"
        string patient_name_extracted
        string diagnosis
        string facility_extracted
        date date_extracted
        jsonb itemised_charges
        numeric total_amount_extracted
        string llm_model
        string prompt_version
        timestamp extracted_at
    }

    DECISIONS {
        uuid id PK
        uuid claim_id FK
        enum outcome "ACCEPTED|REJECTED|NEEDS_REVIEW"
        text reason
        jsonb cited_clauses
        text executive_summary
        float confidence_score
        string model_name
        string prompt_version
        jsonb retrieved_chunks
        timestamp decided_at
    }

    REVIEWS {
        uuid id PK
        uuid claim_id FK
        uuid reviewer_id FK
        enum outcome "APPROVED|REJECTED|OVERRIDE"
        text comment
        enum previous_status
        enum new_status
        timestamp reviewed_at
    }

    EXCLUSIONS {
        uuid id PK
        string term UK
        text description
        boolean is_active
        uuid created_by FK
        timestamp created_at
    }

    HANDBOOK_VERSIONS {
        uuid id PK
        string version_tag
        string file_path
        int chunk_count
        string faiss_index_path
        boolean is_active
        uuid uploaded_by FK
        timestamp uploaded_at
    }

    AUDIT_LOGS {
        uuid id PK
        uuid claim_id FK
        uuid user_id FK
        string action
        jsonb payload
        string ip_address
        timestamp logged_at
    }

    USERS ||--o{ CLAIMS : "submits"
    CLAIMS ||--o{ CLAIM_DOCUMENTS : "has"
    CLAIMS ||--|| EXTRACTED_FIELDS : "has one"
    CLAIMS ||--o{ DECISIONS : "receives"
    CLAIMS ||--o{ REVIEWS : "reviewed by"
    USERS ||--o{ REVIEWS : "performs"
    USERS ||--o{ EXCLUSIONS : "created_by"
    USERS ||--o{ HANDBOOK_VERSIONS : "uploaded_by"
    CLAIMS ||--o{ AUDIT_LOGS : "tracked in"
    USERS ||--o{ AUDIT_LOGS : "actor"
```

## Index Strategy

| Index | Table | Column(s) | Purpose |
|---|---|---|---|
| `ix_claims_status` | claims | status | Reviewer queue filter |
| `ix_claims_created_at` | claims | created_at | Time-sorted list |
| `ix_claims_user_id` | claims | user_id | User's own claims |
| `ix_claims_confidence_score` | claims | confidence_score | Low-confidence queue |
| `ix_exclusions_term` | exclusions | term (UNIQUE) | Fast fuzzy lookup |
| `ix_users_email` | users | email (UNIQUE) | Login lookup |

## Key Design Decisions

- **UUID PKs** — no integer enumeration attacks; safe to expose in REST URLs
- **JSONB** for `itemised_charges`, `cited_clauses`, `retrieved_chunks`, `payload` — variable structure without extra tables
- **Separate `extracted_fields`** (1:1 with claim) — clean audit: form input vs OCR/LLM output
- **`handbook_versions.is_active`** — only one handbook active; rollback is a single UPDATE
- **`audit_logs.payload` JSONB** — stores full LLM decision context per call for explainability
- **`reviews` previous/new status** — human override history without losing the AI decision

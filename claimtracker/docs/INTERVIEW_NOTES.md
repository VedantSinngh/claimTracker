# Interview Notes — ClaimTracker

## Technology Choices

| Technology | Why Chosen | Alternatives Considered |
|---|---|---|
| **FastAPI** | Async-native, auto OpenAPI docs, Depends() DI, Pydantic integration | Flask (no async), Django REST (heavier ORM) |
| **SQLAlchemy 2.0** | Async support, dual PostgreSQL/SQLite, mature ecosystem | Tortoise ORM, SQLModel (less mature) |
| **Groq (Llama 3)** | Fastest inference API (~200ms), free tier, open model | OpenAI (cost), Anthropic (cost), local Ollama (slower) |
| **FAISS** | In-memory cosine search, zero infrastructure, great for <10K vectors | pgvector (needs PG extension), Pinecone (SaaS cost), Weaviate (infrastructure) |
| **sentence-transformers** | Best quality/size ratio for embedding, MiniLM-L6 is 80MB | OpenAI embeddings (cost per call), TF-IDF (lower quality) |
| **pytesseract** | Free, open-source OCR | AWS Textract (cost), Google Vision (cost), EasyOCR (Python-native but slower) |
| **pdfplumber** | Best digital PDF text extraction in Python | PyMuPDF (C dependency), pdfminer (slower) |
| **rapidfuzz** | C++ under the hood, 10x faster than fuzzywuzzy | python-Levenshtein, thefuzz |
| **Next.js App Router** | Full-stack React, SSR, file-based routing | Vite+React (no SSR), Angular (heavier) |
| **n8n** | Visual workflow automation, self-hosted, webhook-native | Zapier (SaaS cost), custom scripts (no UI) |

## Trade-offs

| Trade-off | Decision | Downside |
|---|---|---|
| FAISS vs pgvector | FAISS for simplicity | Must reload index on restart; can't scale past single-server |
| Background task vs queue | FastAPI BackgroundTasks | No retry, no dead letter queue, single-process |
| Regex PII vs NER | Regex for speed | Misses novel PII patterns |
| SQLite for dev | Fast iteration | No concurrent writes, no JSONB (uses TEXT) |
| LLM for extraction | Flexible, handles varied bill formats | Cost per call, latency, hallucination risk |

## Scaling Plan (10,000 claims/day)

```
Current Architecture          →  Scaled Architecture
─────────────────────────────────────────────────────
FastAPI BackgroundTasks       →  Celery + Redis/SQS
FAISS (in-memory)             →  pgvector or Qdrant (persistent, multi-node)
Single PostgreSQL             →  RDS with read replicas
File storage (disk)           →  S3 with pre-signed URLs
Single EC2                    →  ECS/EKS auto-scaling group
Sentence-transformers local   →  Embedding API (batch) or GPU instance
n8n single instance           →  n8n with external PostgreSQL
No caching                    →  Redis cache for handbook chunks, user sessions
```

### Specific changes at scale:
1. **Task queue**: Replace BackgroundTasks with Celery + SQS. Dead letter queue for failed claims. Retry logic with exponential backoff.
2. **Vector DB**: pgvector alongside PostgreSQL, or Qdrant for dedicated vector search. Supports multi-handbook search and dynamic updates.
3. **Caching**: Redis for frequently-accessed handbook chunks (TTL on handbook version change). LLM response caching for identical diagnoses.
4. **Horizontal scaling**: Stateless FastAPI behind ALB, auto-scaling group based on CPU/queue depth.
5. **Batch processing**: Nightly batch for bulk claims; real-time for individual submissions.

## Known Limitations

1. **OCR accuracy**: pytesseract on scanned PDFs is ~85-95% accurate. Handwritten bills will fail. A production system needs AWS Textract or similar.
2. **LLM hallucination**: Despite the exclusion pre-check and prompt engineering, the LLM can still hallucinate citations. The confidence threshold mitigates this but doesn't eliminate it.
3. **Single handbook**: Current design assumes one active handbook. Multi-policy support (different plans) would need per-policy FAISS indexes.
4. **No model monitoring**: No automated drift detection or accuracy tracking against human reviewer decisions.
5. **PII masking is regex-only**: Novel formats (e.g., foreign ID numbers) will be missed.

## Future Work

1. **Model evaluation framework**: Track LLM accuracy against human reviewer ground truth
2. **Multi-language OCR**: Extend to non-English bills
3. **Claim categorization**: Auto-categorize claims (emergency, routine, specialist) for priority routing
4. **Patient portal**: Let patients track their claim status in real-time
5. **Fraud detection**: Flag suspiciously similar claims or unusual patterns
6. **A/B testing prompts**: Test different prompt versions and measure accuracy changes

## Likely Follow-up Questions

**Q: Why did you check exclusions with rules instead of only the LLM?**
A: The LLM hallucinated approvals for excluded conditions in testing. Cosmetic surgery was approved twice because the handbook clause was phrased ambiguously. The deterministic check catches this with 100% reliability before the LLM ever sees the claim.

**Q: How do you stop the model from hallucinating an approval?**
A: Four layers: (1) deterministic exclusion check, (2) strict JSON schema in the prompt, (3) confidence threshold → NEEDS_REVIEW, (4) human reviewer queue. No single layer is foolproof; defense in depth.

**Q: What happens if the OCR reads the amount wrong?**
A: The AmountCheckValidator has a 5% tolerance. If the extracted amount is wildly wrong (e.g., $0), it routes to NEEDS_REVIEW rather than auto-rejecting. The human reviewer sees the original bill.

**Q: How do you protect patient data?**
A: PII masking before LLM calls. API keys in env vars. Audit logs don't store raw PII. JWT auth with role-based access. In production: HTTPS everywhere, encrypted DB at rest, VPC isolation.

**Q: How would you handle 10,000 claims a day?**
A: Celery task queue, horizontal scaling behind ALB, pgvector for persistent vector search, S3 for file storage, Redis for caching, read replicas for analytics queries.

**Q: How would you measure the accuracy of the system?**
A: Compare AI decisions against human reviewer overrides. Track: false approval rate, false rejection rate, NEEDS_REVIEW rate, override rate. Set up automated reports and alerting on drift.

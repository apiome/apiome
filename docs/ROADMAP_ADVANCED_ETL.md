# Apiome Suite — Advanced ETL & Data Loading Roadmap Ideas

This document captures potential new products for the Apiome enterprise suite focused on **ETL, data ingestion, extraction, and big-data transport**. These ideas are based on analysis of the existing UI mockup suite, the `apiome-db` schema model (where `classes` and `class_properties` define dynamically-generated table schemas), and common enterprise data engineering requirements. Every proposed product ultimately writes to, reads from, or routes data through apiome-db instances. Each product fills a genuine gap not covered by the existing `import`, `data-transform`, `connect`, `db`, `detective`, or `harvest` mockups.

---

## Summary Matrix

| Product | Directory | Category | Complexity | Enterprise Value |
|---|---|---|---|---|
| **Forge** | `/mockups/forge` | Pipeline | High | ⭐⭐⭐⭐⭐ |
| **Temporal** | `/mockups/temporal` | Orchestration | High | ⭐⭐⭐⭐⭐ |
| **Scheduler** | `/mockups/job-scheduler` | Orchestration | Medium | ⭐⭐⭐⭐ |
| **Bulk** | `/mockups/bulk` | Ingestion | High | ⭐⭐⭐⭐⭐ |
| **Stream** | `/mockups/stream` | Ingestion | High | ⭐⭐⭐⭐⭐ |
| **CDC** | `/mockups/cdc` | Ingestion | High | ⭐⭐⭐⭐ |
| **File Gateway** | `/mockups/file-gateway` | Ingestion | Medium | ⭐⭐⭐⭐ |
| **Data Federate** | `/mockups/data-federate` | Query | High | ⭐⭐⭐⭐⭐ |
| **DeltaSync** | `/mockups/delta-sync` | Sync | Medium | ⭐⭐⭐⭐ |
| **Profile (Data)** | `/mockups/data-profile` | Discovery | Medium | ⭐⭐⭐⭐⭐ |
| **Quality** | `/mockups/data-quality` | Governance | Medium | ⭐⭐⭐⭐⭐ |
| **Reverse** | `/mockups/reverse-etl` | Egress | Medium | ⭐⭐⭐⭐ |
| **Wormhole** | `/mockups/wormhole` | Governance | Medium | ⭐⭐⭐⭐ |

---

## Recommended Priority Order

Based on market demand, natural fit with the existing apiome-db schema model, and lowest incremental build cost:

1. **Forge** — the ETL pipeline canvas is the anchor product for the entire data-loading suite; every other product feeds into or is triggered from a Forge pipeline; DataFusion and Spark support are already referenced in the `data-transform/` mockup, making this a natural extension
2. **Profile (Data)** — highest leverage per effort; generating apiome Class definitions from source data samples dramatically lowers the barrier to entry for new users and makes every other ingestion product easier to configure; no similar mockup exists today
3. **Quality** — universally demanded by enterprise data governance teams; DQ rules attached to Class definitions are a unique differentiator because quality policy travels with the schema version; directly reinforces the value of the apiome schema model
4. **Bulk** — addresses the single most common enterprise data loading pattern (file-based batch loads from S3/cloud object stores); DataFusion and Spark references already present in `data-transform/` Spark Jobs mockup
5. **Temporal** — critical for any long-running load job that needs durability guarantees beyond what a cron scheduler provides; positions apiome-db as a reliable enterprise data platform rather than a lightweight tool
6. **Stream** — completes the real-time ingestion story alongside CDC; Kafka integration is one of the top-asked-for capabilities in enterprise data platforms
7. **CDC** — enables near-zero-latency replication from operational databases; high value for analytics-on-operational-data use cases; Debezium/PgLogical are mature and well-understood
8. **Data Federate** — DataFusion as a virtual query engine is a strong differentiator; allows analysts to query data in place before committing to full loads; powers exploratory use cases that drive adoption
9. **DeltaSync** — fills the gap between full-load (Bulk) and real-time (CDC/Stream); the most common production pattern for daily/hourly ETL from OLTP sources
10. **Scheduler** — high operational value once multiple pipeline products exist; best built after Forge and Temporal are established so the scheduling surface has real jobs to manage
11. **File Gateway** — solves a very common enterprise pain point (file drops from legacy systems); medium complexity with high practical value for brownfield integrations
12. **Reverse** — completes the data lifecycle story; high value for RevOps and marketing teams; best positioned after the ingestion products are mature
13. **Wormhole** — primarily an enterprise/regulated-industry product; high compliance value; best built after the core ingestion and quality products establish apiome-db as a trustworthy data store

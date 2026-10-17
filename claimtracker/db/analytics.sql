-- =============================================================================
-- ClaimTracker Analytics Queries
-- Database: PostgreSQL 16
-- All queries run against the production schema defined in migration 0001-0003
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. Approval vs Rejection Rate Per Month
--    GROUP BY + aggregates — shows monthly trends for dashboards
-- -----------------------------------------------------------------------------
SELECT
    DATE_TRUNC('month', created_at)    AS month,
    COUNT(*) FILTER (WHERE status = 'ACCEPTED')  AS accepted,
    COUNT(*) FILTER (WHERE status = 'REJECTED')  AS rejected,
    COUNT(*) FILTER (WHERE status = 'NEEDS_REVIEW') AS needs_review,
    COUNT(*)                            AS total,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE status = 'ACCEPTED') / NULLIF(COUNT(*), 0),
        2
    )                                  AS acceptance_rate_pct
FROM claims
GROUP BY DATE_TRUNC('month', created_at)
ORDER BY month DESC;


-- -----------------------------------------------------------------------------
-- 2a. Top 5 Rejection Reasons — Window Function version (RANK() OVER)
--     Demonstrates analytic/window functions for interviews
-- -----------------------------------------------------------------------------
SELECT
    reason,
    rejection_count,
    RANK() OVER (ORDER BY rejection_count DESC) AS rank
FROM (
    SELECT
        reason,
        COUNT(*) AS rejection_count
    FROM claims
    WHERE status = 'REJECTED'
    GROUP BY reason
) ranked_reasons
ORDER BY rank
LIMIT 5;


-- -----------------------------------------------------------------------------
-- 2b. Top 5 Rejection Reasons — CTE version (same result, different style)
--     Demonstrates readability of CTEs vs subqueries
-- -----------------------------------------------------------------------------
WITH rejection_counts AS (
    SELECT
        reason,
        COUNT(*) AS rejection_count
    FROM claims
    WHERE status = 'REJECTED'
    GROUP BY reason
),
ranked AS (
    SELECT
        reason,
        rejection_count,
        RANK() OVER (ORDER BY rejection_count DESC) AS rank
    FROM rejection_counts
)
SELECT reason, rejection_count, rank
FROM ranked
WHERE rank <= 5
ORDER BY rank;


-- -----------------------------------------------------------------------------
-- 3. Average Processing Time Per Status — CTE version
--    Measures how long (in seconds and human-readable) each pipeline
--    stage takes on average; useful for SLA monitoring
-- -----------------------------------------------------------------------------
WITH processing_times AS (
    SELECT
        status,
        EXTRACT(EPOCH FROM (updated_at - created_at)) AS seconds_taken
    FROM claims
    WHERE status IN ('ACCEPTED', 'REJECTED', 'NEEDS_REVIEW')
      AND updated_at > created_at
)
SELECT
    status,
    COUNT(*)                                    AS claim_count,
    ROUND(AVG(seconds_taken)::NUMERIC, 2)       AS avg_seconds,
    ROUND((AVG(seconds_taken) / 60)::NUMERIC, 2) AS avg_minutes,
    ROUND(MIN(seconds_taken)::NUMERIC, 2)       AS min_seconds,
    ROUND(MAX(seconds_taken)::NUMERIC, 2)       AS max_seconds
FROM processing_times
GROUP BY status
ORDER BY avg_seconds DESC;


-- -----------------------------------------------------------------------------
-- 4. Claims Per User — JOIN version
--    Three-table join: users → roles (INNER, the role name lives in the
--    lookup table since migration 0004) and users → claims (LEFT, so a user
--    with no claims would still appear before the HAVING filter removes them).
--    Demonstrates multi-table JOINs, GROUP BY, HAVING, and CASE WHEN.
-- -----------------------------------------------------------------------------
SELECT
    u.id                                                        AS user_id,
    u.full_name,
    u.email,
    r.name                                                      AS role,
    COUNT(c.id)                                                 AS total_claims,
    SUM(CASE WHEN c.status = 'ACCEPTED'     THEN 1 ELSE 0 END) AS accepted,
    SUM(CASE WHEN c.status = 'REJECTED'     THEN 1 ELSE 0 END) AS rejected,
    SUM(CASE WHEN c.status = 'NEEDS_REVIEW' THEN 1 ELSE 0 END) AS needs_review,
    SUM(CASE WHEN c.status = 'PENDING'      THEN 1 ELSE 0 END) AS pending,
    SUM(c.claim_amount)                                         AS total_claimed_amount,
    AVG(c.confidence_score)                                     AS avg_confidence
FROM users u
JOIN roles r      ON r.id = u.role_id
LEFT JOIN claims c ON c.user_id = u.id
WHERE r.name = 'user'   -- claimants only; reviewers/admins do not file claims
GROUP BY u.id, u.full_name, u.email, r.name
HAVING COUNT(c.id) > 0
ORDER BY total_claims DESC;


-- -----------------------------------------------------------------------------
-- 5. Claims Per User — Subquery version (same result as query 4)
--    Demonstrates how the same logic can be expressed as a subquery.
--    This is what the query planner may rewrite a CTE as anyway.
-- -----------------------------------------------------------------------------
SELECT
    u.full_name,
    u.email,
    user_stats.total_claims,
    user_stats.accepted,
    user_stats.rejected
FROM users u
JOIN (
    SELECT
        user_id,
        COUNT(*)                                                  AS total_claims,
        SUM(CASE WHEN status = 'ACCEPTED' THEN 1 ELSE 0 END)     AS accepted,
        SUM(CASE WHEN status = 'REJECTED' THEN 1 ELSE 0 END)     AS rejected
    FROM claims
    GROUP BY user_id
) user_stats ON user_stats.user_id = u.id
ORDER BY user_stats.total_claims DESC;

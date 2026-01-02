# Vizzy Database Migrations

This directory contains database migrations for the Vizzy application.

## Migration Strategy

Vizzy uses a simple file-based migration system. Migrations are numbered sequentially and designed to be idempotent (safe to run multiple times).

### Running Migrations

```bash
# Run a specific migration
psql vizzy < scripts/migrations/040_phase8_foundation.sql

# Run all migrations in order
for f in scripts/migrations/*.sql; do psql vizzy < "$f"; done

# For fresh databases, use init_db.sql instead (includes all schema changes)
psql vizzy < scripts/init_db.sql
```

### Migration Naming Convention

- `NNN_description.sql` where NNN is a 3-digit number
- Numbers represent execution order
- Use gaps (020, 025, 030) to allow insertions

### Current Migrations

| Migration | Description | Phase |
|-----------|-------------|-------|
| 020_performance_indexes.sql | Performance optimization indexes | 7-003 |
| 025_edge_classification.sql | Build vs runtime edge classification | 8A-001 |
| 030_top_level_identification.sql | Top-level package identification | 8A-002 |
| 035_closure_contribution.sql | Closure contribution calculation | 8A-003 |
| 040_phase8_foundation.sql | Consolidated Phase 8A migration | 8A-006 |

### Schema Version Tracking

The `schema_version` table tracks which migrations have been applied:

```sql
SELECT * FROM schema_version ORDER BY applied_at;
```

### Writing New Migrations

1. Use `IF NOT EXISTS` and `IF EXISTS` for idempotency
2. Wrap in `BEGIN;` / `COMMIT;` for atomicity
3. Include verification queries as comments
4. Update `init_db.sql` with the new schema for fresh installs
5. Add a corresponding entry to `schema_version`

### Rollback Strategy

Migrations are designed to be forward-only. If a rollback is needed:

1. Create a new migration that reverses the changes
2. Document the rollback in the migration comments
3. Test thoroughly before applying to production

# Vizzy Implementation - Task Index & Assignment

## Quick Reference

This document provides a quick reference for all tasks aligned with the existing project phase structure from PRD.md.

**Task ID Convention**: `{Phase}-{Section?}-{Number}` (e.g., `3-001`, `8A-001`)

---

## Task Assignment Board

### Ready for Assignment (No Dependencies)

| Task ID | Task Name | Est. Hours | Phase Document |
|---------|-----------|------------|----------------|
| 3-001 | Loop Detection (Tarjan's SCC) | 6h | `PHASE_3_COMPLETION.md` |
| 3-002 | Redundant Link Detection | 6h | `PHASE_3_COMPLETION.md` |
| 4-001 | Eager Metadata Fetching | 8h | `PHASE_4_COMPLETION.md` |
| 5-001 | Full Diff Between Hosts | 8h | `PHASE_5_HOST_COMPARISON.md` |
| 7-001 | Pan/Zoom for Graphs | 6h | `PHASE_7_POLISH.md` |
| 7-002 | Keyboard Navigation | 4h | `PHASE_7_POLISH.md` |
| 7-003 | Performance Optimization | 8h | `PHASE_7_POLISH.md` |
| 7-004 | URL State Management | 4h | `PHASE_7_POLISH.md` |
| 8A-001 | Edge Classification | 8h | `PHASE_8_QUESTION_DRIVEN.md` |
| 8A-002 | Top-Level Package ID | 6h | `PHASE_8_QUESTION_DRIVEN.md` |
| 8A-004 | Baseline System | 6h | `PHASE_8_QUESTION_DRIVEN.md` |
| 8A-005 | Module Attribution | 6h | `PHASE_8_QUESTION_DRIVEN.md` |
| 8B-001 | Dashboard Design | 4h | `PHASE_8_QUESTION_DRIVEN.md` |
| 8C-001 | Treemap Design | 4h | `PHASE_8_QUESTION_DRIVEN.md` |
| 8D-001 | Matrix Design | 3h | `PHASE_8_QUESTION_DRIVEN.md` |
| 8E-004 | Why Chain UI Design | 4h | `PHASE_8_QUESTION_DRIVEN.md` |

### Blocked (Waiting on Dependencies)

| Task ID | Blocked By | Unblocks |
|---------|------------|----------|
| 5-002 | 5-001 | - |
| 5-003 | 5-001 | - |
| 5-004 | 5-001 | 8F-003, 8F-004 |
| 8A-003 | 8A-001 | 8B-002, 8C-002, 8A-008 |
| 8A-006 | 8A-001, 8A-002 | 8A-007 |
| 8A-007 | 8A-006 | - |
| 8A-008 | 8A-003 | - |
| 8B-002 | 8A-003 | 8B-003 |
| 8B-003 | 8B-001, 8B-002 | 8H-001 |
| 8C-002 | 8A-003 | 8C-003 |
| 8C-003 | 8C-001, 8C-002 | 8C-004 |
| 8C-004 | 8C-003 | - |
| 8D-002 | 8A-001 | 8D-003 |
| 8D-003 | 8D-001, 8D-002 | 8D-004 |
| 8E-001 | 8A-002 | 8E-002 |
| 8E-002 | 8E-001 | 8E-003, 8E-008 |
| 8E-003 | 8E-002 | 8E-005, 8E-007, 8G-003 |
| 8E-005 | 8E-003 | 8E-006 |
| 8E-006 | 8E-004, 8E-005 | 8E-009, 8E-010, 8H-001 |
| 8F-001 | 5-001 | - |
| 8F-002 | 5-001 | - |
| 8F-003 | 5-004 | - |
| 8F-004 | 8A-004, 5-004 | - |
| 8G-001 | - | 8G-002 |
| 8G-002 | 8G-001 | - |
| 8G-003 | 8E-003 | 8G-004 |
| 8G-004 | 8G-003 | - |
| 8H-001 | 8B-003, 8E-006 | 8H-002, 8H-003, 8H-004 |

---

## Assignment Log

| Date | Task ID | Assigned To | Status | Notes |
|------|---------|-------------|--------|-------|
| - | - | - | - | No assignments yet |

---

## How to Assign a Task

1. **Check dependencies** in the blocked table above
2. **Select a "Ready" task** from the first table
3. **Provide the agent** with:
   - The phase document from `tasks/{PHASE_DOCUMENT}`
   - Access to relevant source files (listed in task)
   - The project context: `PROJECT_STATUS.md`

4. **Update this log** with assignment
5. **When complete**, update `PROJECT_STATUS.md`

---

## Task Completion Checklist

When an agent completes a task:

1. ☐ All acceptance criteria met
2 ☐ Code follows existing patterns
3 ☐ No linting errors
4 ☐ Documentation updated if needed
5 ☐ Assignment log updated
6 ☐ PROJECT_STATUS.md updated
7 ☐ Dependent tasks unblocked

---

## Recommended Sprint Plan

### Sprint 1: Complete Existing Phases (1 week)
```
3-001 ─┬─→ (parallel)
3-002 ─┤
4-001 ─┘
```
All three tasks are independent and can be parallelized.

### Sprint 2: Phase 5 Host Comparison (1 week)
```
5-001 → 5-004 → 5-002
             → 5-003
```
5-001 (full diff) is the foundation.

### Sprint 3: Phase 8A Data Model (1 week)
```
8A-001 ─┬─→ 8A-006 → 8A-007
8A-002 ─┘      ↓
         8A-003 → 8A-008
```
Edge classification and top-level ID enable migrations and contribution calc.

### Sprint 4: Dashboard & Treemap (1.5 weeks)
```
8B-001 → 8B-002 → 8B-003
8C-001 → 8C-002 → 8C-003 → 8C-004
```
These can run in parallel after 8A-003 completes.

### Sprint 5: Why Chain (1.5 weeks)
```
8E-001 → 8E-002 → 8E-003 → 8E-005 → 8E-006
8E-004 ────────────────────────────→ 8E-006
```
UI design (8E-004) can be done early, in parallel.

### Sprint 6: Polish (1 week)
```
7-001, 7-002, 7-003, 7-004 (all parallel)
8H-001 → 8H-002, 8H-003, 8H-004
```

---

## Parallel Work Opportunities

These task groups can be worked simultaneously by different agents:

**Group A: Analysis Backend**
- 3-001, 3-002, 4-001 (Sprint 1)
- 8A-001, 8A-002, 8A-005 (Sprint 3)

**Group B: Comparison Backend**
- 5-001, 5-002, 5-003 (Sprint 2)
- 8F-001, 8F-002 (after 5-001)

**Group C: UI/Design**
- 8B-001, 8C-001, 8D-001, 8E-004 (Sprint 3-4)
- 7-002, 7-004 (Sprint 6)

**Group D: Data Services**
- 8A-003, 8B-002, 8C-002 (Sprint 4)
- 8E-002, 8E-003 (Sprint 5)

**Group E: Frontend Build**
- 8B-003, 8C-003, 8E-006 (after designs)
- 7-001, 7-003 (Sprint 6)

---

## Phase Document Map

| Phases | Document | Tasks |
|--------|----------|-------|
| 3 | `PHASE_3_COMPLETION.md` | 3-001, 3-002 |
| 4 | `PHASE_4_COMPLETION.md` | 4-001 |
| 5 | `PHASE_5_HOST_COMPARISON.md` | 5-001 through 5-004 |
| 7 | `PHASE_7_POLISH.md` | 7-001 through 7-004 |
| 8A-8H | `PHASE_8_QUESTION_DRIVEN.md` | 8A-* through 8H-* |

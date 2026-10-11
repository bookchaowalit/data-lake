-- Migration 056: use a normal weekly planning name in the live portfolio view.
-- AI remains an optional capability inside the cycle, not a separate sprint type.

UPDATE goals
SET title = 'Weekly Planning Cycle: evidence-backed delivery',
    description = 'Plan, execute, and review learning, product, operations, and AI-assisted work every week with clear outcomes, evidence, quality, cost, and risk checks.',
    notes = 'Portfolio control objective. AI is optional support inside the cycle, not a separate sprint type.'
WHERE title = 'Adaptive Portfolio Operating System: evidence-backed delivery cadence';

UPDATE operating_cycles
SET name = 'Weekly Planning Cycle — Systems Foundations',
    focus = 'Choose one weekly outcome, execute a small set of committed work, and review evidence, quality, cost, and risk.',
    source = 'weekly-planning-cycle',
    notes = 'Planned only. Start explicitly after reviewing the objective, capacity, KPI guardrails, and task commitment. AI is optional support, not a separate sprint type.'
WHERE slug = 'adaptive-foundation-2026-w34';

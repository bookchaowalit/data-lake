-- Migration 055: classify the portfolio operating objective under operations.

UPDATE goals
SET domain = 'book-operations'
WHERE title = 'Adaptive Portfolio Operating System: evidence-backed delivery cadence'
  AND domain = 'book-ai';

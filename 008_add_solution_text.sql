-- =====================================================
-- Migration: Add solution_text column to ticket_embeddings
-- =====================================================
-- This column stores the AI-summarized, masked solution text (from comments)
-- separate from the embedding (which is generated from title+description only)

-- Add solution_text column
ALTER TABLE ticket_embeddings 
ADD COLUMN IF NOT EXISTS solution_text TEXT;

-- Add comment to explain the column
COMMENT ON COLUMN ticket_embeddings.solution_text IS 
'AI-summarized solution text from public comments. Sensitive data (emails, phones, transaction IDs, names, amounts) are automatically masked by Groq LLM. This is NOT embedded - only stored for display in similarity search results.';
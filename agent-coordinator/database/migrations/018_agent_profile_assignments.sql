-- Migration 018: Explicit agent profile assignments
-- Dependencies: 007_agent_profiles.sql
--
-- Previously, all agents fell back to type-based profile lookup
-- (first profile by created_at for the agent_type). This meant
-- claude-remote got claude_code_cli (trust 3) instead of
-- claude_code_web_implementer (trust 2). This migration creates
-- explicit assignments matching agents.yaml definitions.

-- =============================================================================
-- Add missing profiles (local variants for codex and gemini)
-- =============================================================================

INSERT INTO agent_profiles (name, description, agent_type, trust_level, allowed_operations, max_file_modifications)
VALUES
    ('codex_local_worker', 'Local Codex CLI agent with full trust', 'codex', 3,
     ARRAY['acquire_lock', 'release_lock', 'check_locks', 'get_work', 'complete_work',
           'submit_work', 'write_handoff', 'read_handoff', 'register_session',
           'discover_agents', 'heartbeat', 'remember', 'recall', 'check_guardrails',
           'get_my_profile', 'query_audit'], 100),
    ('gemini_local_worker', 'Local Gemini CLI agent with full trust', 'gemini', 3,
     ARRAY['acquire_lock', 'release_lock', 'check_locks', 'get_work', 'complete_work',
           'submit_work', 'write_handoff', 'read_handoff', 'register_session',
           'discover_agents', 'heartbeat', 'remember', 'recall', 'check_guardrails',
           'get_my_profile', 'query_audit'], 100),
    ('gemini_cloud_worker', 'Remote Gemini agent with standard trust', 'gemini', 2,
     ARRAY['acquire_lock', 'release_lock', 'check_locks', 'get_work', 'complete_work',
           'submit_work', 'register_session', 'heartbeat', 'remember', 'recall',
           'check_guardrails', 'get_my_profile'], 50)
ON CONFLICT (name) DO NOTHING;

-- =============================================================================
-- Create explicit profile assignments (agents.yaml → DB)
-- =============================================================================
-- These map agent_id (from COORDINATION_API_KEY_IDENTITIES) to the correct
-- profile, overriding the type-based fallback.

INSERT INTO agent_profile_assignments (agent_id, profile_id)
SELECT 'claude-local', id FROM agent_profiles WHERE name = 'claude_code_cli'
ON CONFLICT (agent_id) DO UPDATE SET profile_id = EXCLUDED.profile_id;

INSERT INTO agent_profile_assignments (agent_id, profile_id)
SELECT 'claude-remote', id FROM agent_profiles WHERE name = 'claude_code_web_implementer'
ON CONFLICT (agent_id) DO UPDATE SET profile_id = EXCLUDED.profile_id;

INSERT INTO agent_profile_assignments (agent_id, profile_id)
SELECT 'codex-local', id FROM agent_profiles WHERE name = 'codex_local_worker'
ON CONFLICT (agent_id) DO UPDATE SET profile_id = EXCLUDED.profile_id;

INSERT INTO agent_profile_assignments (agent_id, profile_id)
SELECT 'codex-remote', id FROM agent_profiles WHERE name = 'codex_cloud_worker'
ON CONFLICT (agent_id) DO UPDATE SET profile_id = EXCLUDED.profile_id;

INSERT INTO agent_profile_assignments (agent_id, profile_id)
SELECT 'gemini-local', id FROM agent_profiles WHERE name = 'gemini_local_worker'
ON CONFLICT (agent_id) DO UPDATE SET profile_id = EXCLUDED.profile_id;

INSERT INTO agent_profile_assignments (agent_id, profile_id)
SELECT 'gemini-remote', id FROM agent_profiles WHERE name = 'gemini_cloud_worker'
ON CONFLICT (agent_id) DO UPDATE SET profile_id = EXCLUDED.profile_id;

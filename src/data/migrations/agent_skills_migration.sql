-- Create the agent_skills table
CREATE TABLE IF NOT EXISTS public.agent_skills
(
    agent_skill_id serial NOT NULL,
    user_id character varying(36) NOT NULL,
    area_id bigint NOT NULL,
    proficiency_level character varying(50) DEFAULT 'intermediate',
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT agent_skills_pkey PRIMARY KEY (agent_skill_id),
    CONSTRAINT agent_skills_unique UNIQUE (user_id, area_id),
    CONSTRAINT agent_skills_area_id_fkey FOREIGN KEY (area_id)
        REFERENCES public.areas_of_concern (area_id)
        ON DELETE CASCADE
);

-- Indexes for faster lookups
CREATE INDEX IF NOT EXISTS idx_agent_skills_user_id 
    ON public.agent_skills(user_id);

CREATE INDEX IF NOT EXISTS idx_agent_skills_area_id 
    ON public.agent_skills(area_id);

-- Populate default skills for existing agents and leads
INSERT INTO public.agent_skills (user_id, area_id, proficiency_level)
SELECT 
    u.id::text,
    a.area_id,
    'intermediate'
FROM auth.users u
JOIN auth.roles r ON u.role_id = r.id
CROSS JOIN public.areas_of_concern a
WHERE r.name IN ('support_agent', 'team_lead')
ON CONFLICT (user_id, area_id) DO NOTHING;

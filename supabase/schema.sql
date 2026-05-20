-- HireLens SaaS schema for Supabase Postgres.
-- Run this in Supabase SQL Editor before deploying the Vercel app.

create extension if not exists pgcrypto;

create table if not exists public.organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.organization_members (
  organization_id uuid not null references public.organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('owner', 'admin', 'member')),
  created_at timestamptz not null default now(),
  primary key (organization_id, user_id)
);

create table if not exists public.jobs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  title text not null,
  headcount integer not null default 1,
  arrival_date date,
  status text not null check (status in ('停止', '在进行', '已完成')),
  jd_text text not null,
  created_by uuid references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.job_personas (
  job_id uuid primary key references public.jobs(id) on delete cascade,
  age_range text,
  gender_preference text,
  work_years text,
  min_education text,
  job_hop_frequency text,
  persona_keywords jsonb not null default '[]'::jsonb,
  compliance_note text
);

create table if not exists public.job_requirements (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.jobs(id) on delete cascade,
  type text not null check (type in ('must', 'bonus')),
  field_key text not null,
  field_label text not null,
  field_value text not null,
  weight numeric not null default 1,
  is_knockout boolean not null default false,
  sort_order integer not null default 0
);

create table if not exists public.screening_skills (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  name text not null,
  category text not null default '通用',
  description text,
  instruction text not null,
  strictness text not null default 'balanced',
  status text not null default 'active' check (status in ('active', 'paused')),
  is_system boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.resumes (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  candidate_name text not null,
  file_name text,
  file_url text,
  parsed_text text not null,
  source text not null default 'manual',
  uploaded_by uuid references auth.users(id),
  created_at timestamptz not null default now()
);

create table if not exists public.screening_tasks (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  job_id uuid not null references public.jobs(id) on delete cascade,
  status text not null check (status in ('pending', 'completed', 'failed')),
  resume_count integer not null default 0,
  created_by uuid references auth.users(id),
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

create table if not exists public.screening_results (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  task_id uuid not null references public.screening_tasks(id) on delete cascade,
  resume_id uuid not null references public.resumes(id) on delete cascade,
  job_id uuid not null references public.jobs(id) on delete cascade,
  conclusion text not null check (conclusion in ('非常匹配', '一般匹配', '不匹配')),
  score integer not null,
  matched_points jsonb not null default '[]'::jsonb,
  missing_points jsonb not null default '[]'::jsonb,
  risk_points jsonb not null default '[]'::jsonb,
  interview_questions jsonb not null default '[]'::jsonb,
  summary text,
  model_name text not null,
  prompt_version text not null,
  review_status text not null default '待复核',
  created_at timestamptz not null default now()
);

create index if not exists idx_jobs_org on public.jobs(organization_id);
create index if not exists idx_resumes_org on public.resumes(organization_id);
create index if not exists idx_results_org on public.screening_results(organization_id);
create index if not exists idx_results_job on public.screening_results(job_id);
create index if not exists idx_screening_skills_org on public.screening_skills(organization_id);

alter table public.organizations enable row level security;
alter table public.organization_members enable row level security;
alter table public.jobs enable row level security;
alter table public.job_personas enable row level security;
alter table public.job_requirements enable row level security;
alter table public.screening_skills enable row level security;
alter table public.resumes enable row level security;
alter table public.screening_tasks enable row level security;
alter table public.screening_results enable row level security;

create or replace function public.is_org_member(org_id uuid)
returns boolean
language sql
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.organization_members m
    where m.organization_id = org_id
      and m.user_id = auth.uid()
  );
$$;

drop policy if exists "members can read organizations" on public.organizations;
create policy "members can read organizations"
on public.organizations for select
using (public.is_org_member(id));

drop policy if exists "members can read organization_members" on public.organization_members;
create policy "members can read organization_members"
on public.organization_members for select
using (public.is_org_member(organization_id));

drop policy if exists "members can read jobs" on public.jobs;
create policy "members can read jobs"
on public.jobs for select
using (public.is_org_member(organization_id));

drop policy if exists "members can read job_personas" on public.job_personas;
create policy "members can read job_personas"
on public.job_personas for select
using (exists (
  select 1 from public.jobs j
  where j.id = job_personas.job_id
    and public.is_org_member(j.organization_id)
));

drop policy if exists "members can read job_requirements" on public.job_requirements;
create policy "members can read job_requirements"
on public.job_requirements for select
using (exists (
  select 1 from public.jobs j
  where j.id = job_requirements.job_id
    and public.is_org_member(j.organization_id)
));

drop policy if exists "members can read screening_skills" on public.screening_skills;
create policy "members can read screening_skills"
on public.screening_skills for select
using (public.is_org_member(organization_id));

drop policy if exists "members can read resumes" on public.resumes;
create policy "members can read resumes"
on public.resumes for select
using (public.is_org_member(organization_id));

drop policy if exists "members can read screening_tasks" on public.screening_tasks;
create policy "members can read screening_tasks"
on public.screening_tasks for select
using (public.is_org_member(organization_id));

drop policy if exists "members can read screening_results" on public.screening_results;
create policy "members can read screening_results"
on public.screening_results for select
using (public.is_org_member(organization_id));

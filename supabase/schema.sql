-- =====================================================================
--  Base de données de la veille de stages (Supabase / PostgreSQL)
--  À coller UNE FOIS dans Supabase > SQL Editor > New query > Run.
--  Le script peut être relancé sans risque (il ne supprime rien).
-- =====================================================================

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------
-- Offres (principales ET doublons ; les doublons partagent le même group_id)
-- ---------------------------------------------------------------------
create table if not exists public.offers (
  id                uuid primary key default gen_random_uuid(),
  group_id          uuid not null,
  is_primary        boolean not null default true,
  dup_reason        text,
  badge             text,                 -- 'Repost' | 'Mise à jour'
  badge_at          timestamptz,

  company           text not null,
  company_raw       text,
  company_category  text,
  company_listed    boolean default true,
  title             text not null,
  title_norm        text,
  city              text,
  cities            text[] default '{}',
  country           text,
  location          text,

  source            text,                 -- 'Site officiel' | 'LinkedIn' | 'Ajout manuel'
  source_id         text unique,
  source_meta       jsonb default '{}'::jsonb,
  url               text,
  apply_url         text,

  posted_at         timestamptz,          -- date de publication annoncée par le site
  first_seen_at     timestamptz not null default now(),  -- détection par la veille
  last_seen_at      timestamptz not null default now(),
  detail_checked_at timestamptz,
  active            boolean not null default true,

  description       text,
  description_hash  text,
  role_type         text,
  roles             text[] default '{}',
  desks             text[] default '{}',
  duration_months   int,
  start_year        int,
  start_month       int,
  start_text        text,
  period_fit        text,                 -- 'OK' | 'À vérifier' | 'Incompatible'
  period_label      text,
  market_score      int,
  relevant          boolean not null default true,
  filter_reason     text,
  manual            boolean default false,

  -- Suivi de candidature (partagé par toutes les offres d'un même groupe)
  status            text not null default 'Nouvelle',
  status_updated_at timestamptz,
  applied_at        timestamptz,
  notes             text,
  favorite          boolean default false,
  deadline          date,

  -- Module IA (vide tant qu'il est désactivé)
  match_score       int,
  match_confidence  text,
  match_strengths   jsonb,
  match_gaps        jsonb,
  match_keywords    jsonb,
  match_summary     text,
  match_at          timestamptz,

  created_at        timestamptz not null default now()
);

create index if not exists offers_group_idx   on public.offers (group_id);
create index if not exists offers_company_idx on public.offers (company);
create index if not exists offers_seen_idx    on public.offers (first_seen_at desc);

-- ---------------------------------------------------------------------
-- Historique des statuts (pour les statistiques)
-- ---------------------------------------------------------------------
create table if not exists public.status_history (
  id         bigint generated always as identity primary key,
  group_id   uuid not null,
  offer_id   uuid,
  status     text not null,
  changed_at timestamptz not null default now()
);
create index if not exists status_history_group_idx on public.status_history (group_id);

-- ---------------------------------------------------------------------
-- Journal des collectes (onglet "Sources" du dashboard)
-- ---------------------------------------------------------------------
create table if not exists public.runs (
  id          bigint generated always as identity primary key,
  source      text not null,
  ok          boolean not null,
  fetched     int, kept int, new int,
  error       text,
  started_at  timestamptz, finished_at timestamptz default now(),
  duration_s  numeric
);
create index if not exists runs_source_idx on public.runs (source, finished_at desc);

create or replace view public.source_last_success
with (security_invoker = true) as
  select source, max(finished_at) as last_ok from public.runs where ok group by source;

-- ---------------------------------------------------------------------
-- Ajouts manuels depuis le dashboard (traités au passage suivant du moteur)
-- ---------------------------------------------------------------------
create table if not exists public.inbox (
  id           uuid primary key default gen_random_uuid(),
  created_at   timestamptz not null default now(),
  company      text,
  title        text,
  url          text,
  location     text,
  text         text,
  origin       text,          -- 'Post LinkedIn' | 'Site' | 'Bouche-à-oreille'...
  posted_at    timestamptz,
  processed    boolean not null default false,
  processed_at timestamptz,
  offer_id     uuid,
  result       text
);

-- ---------------------------------------------------------------------
-- Synchronisation du statut entre une offre et ses doublons
-- ---------------------------------------------------------------------
create or replace function public.sync_group_status() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if pg_trigger_depth() > 1 then
    return new;
  end if;
  if new.status is distinct from old.status
     or new.notes is distinct from old.notes
     or new.favorite is distinct from old.favorite
     or new.deadline is distinct from old.deadline then
    if new.status is distinct from old.status then
      new.status_updated_at := now();
      if new.status = 'Postulée' and new.applied_at is null then
        new.applied_at := now();
      end if;
      insert into public.status_history (group_id, offer_id, status) values (new.group_id, new.id, new.status);
    end if;
    update public.offers
       set status = new.status, status_updated_at = new.status_updated_at, applied_at = new.applied_at,
           notes = new.notes, favorite = new.favorite, deadline = new.deadline
     where group_id = new.group_id and id <> new.id;
  end if;
  return new;
end $$;

drop trigger if exists offers_sync_status on public.offers;
create trigger offers_sync_status before update on public.offers
  for each row execute function public.sync_group_status();

-- ---------------------------------------------------------------------
-- Sécurité : seul un utilisateur connecté (toi) peut lire/modifier.
-- Le moteur utilise la clé "service_role", qui contourne ces règles.
-- ---------------------------------------------------------------------
alter table public.offers         enable row level security;
alter table public.status_history enable row level security;
alter table public.runs           enable row level security;
alter table public.inbox          enable row level security;

drop policy if exists "proprietaire" on public.offers;
create policy "proprietaire" on public.offers for all to authenticated using (true) with check (true);
drop policy if exists "proprietaire" on public.status_history;
create policy "proprietaire" on public.status_history for all to authenticated using (true) with check (true);
drop policy if exists "proprietaire" on public.runs;
create policy "proprietaire" on public.runs for select to authenticated using (true);
drop policy if exists "proprietaire" on public.inbox;
create policy "proprietaire" on public.inbox for all to authenticated using (true) with check (true);

grant select, insert, update, delete on public.offers, public.status_history, public.inbox to authenticated;
grant select on public.runs, public.source_last_success to authenticated;
grant all on public.offers, public.status_history, public.runs, public.inbox, public.source_last_success to service_role;
grant usage, select on all sequences in schema public to service_role;

-- Rien n'est accessible sans connexion
revoke all on public.offers, public.status_history, public.runs, public.inbox from anon;
revoke all on public.source_last_success from anon;

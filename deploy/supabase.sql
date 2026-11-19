-- Run as the project owner in a dedicated Supabase project.
create table if not exists public.geneminer_projects (
  id uuid primary key default gen_random_uuid(),
  owner uuid not null default auth.uid() references auth.users(id) on delete cascade,
  name text not null check (char_length(trim(name)) between 1 and 200),
  species text not null default '' check (char_length(species) <= 200),
  target text not null default '' check (char_length(target) <= 200),
  state text not null default '' check (char_length(state) <= 200),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  payload text not null check (octet_length(payload) <= 33554432)
);
create index if not exists geneminer_projects_owner_updated on public.geneminer_projects(owner, updated_at desc);
alter table public.geneminer_projects enable row level security;
revoke all on public.geneminer_projects from anon, public, authenticated;
grant select, delete on public.geneminer_projects to authenticated;
grant insert (name,species,target,state,payload) on public.geneminer_projects to authenticated;
grant update (name,species,target,state,payload) on public.geneminer_projects to authenticated;

drop policy if exists geneminer_owner on public.geneminer_projects;
create policy geneminer_owner on public.geneminer_projects
  for all to authenticated using (owner = (select auth.uid())) with check (owner = (select auth.uid()));

create or replace function public.geneminer_touch() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.updated_at := pg_catalog.now();
  return new;
end;
$$;
drop trigger if exists geneminer_touch on public.geneminer_projects;
create trigger geneminer_touch before update on public.geneminer_projects
for each row execute function public.geneminer_touch();

create or replace function public.delete_geneminer_account() returns void
language plpgsql security definer set search_path = '' as $$
begin
  if auth.uid() is null then
    raise exception 'Authentication required' using errcode = '42501';
  end if;
  delete from auth.users where id = auth.uid();
end;
$$;
revoke all on function public.delete_geneminer_account() from public, anon;
grant execute on function public.delete_geneminer_account() to authenticated;

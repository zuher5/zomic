-- Run once in the Supabase SQL Editor before enabling account sync.
-- The anon/publishable key is safe for the browser only because RLS is enabled.
create table if not exists public.bookmarks (
  user_id uuid not null references auth.users(id) on delete cascade,
  comic_slug text not null check (char_length(comic_slug) between 1 and 240),
  title text not null default '' check (char_length(title) <= 300),
  cover text not null default '' check (char_length(cover) <= 2000),
  deleted boolean not null default false,
  updated_at timestamptz not null default now(),
  primary key (user_id, comic_slug)
);

alter table public.bookmarks enable row level security;

-- A delayed sync from an offline device must not overwrite a newer edit.
create or replace function public.keep_newest_bookmark_version()
returns trigger
language plpgsql
as $$
begin
  if new.updated_at <= old.updated_at then
    new.title := old.title;
    new.cover := old.cover;
    new.deleted := old.deleted;
    new.updated_at := old.updated_at;
  end if;
  return new;
end;
$$;

drop trigger if exists bookmarks_keep_newest on public.bookmarks;
create trigger bookmarks_keep_newest
  before update on public.bookmarks
  for each row execute function public.keep_newest_bookmark_version();

revoke all on table public.bookmarks from anon;
grant select, insert, update on table public.bookmarks to authenticated;

-- Idempotent policies: users can only read/write their own rows.
drop policy if exists "Users read own bookmarks" on public.bookmarks;
create policy "Users read own bookmarks"
  on public.bookmarks for select to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "Users insert own bookmarks" on public.bookmarks;
create policy "Users insert own bookmarks"
  on public.bookmarks for insert to authenticated
  with check ((select auth.uid()) = user_id);

drop policy if exists "Users update own bookmarks" on public.bookmarks;
create policy "Users update own bookmarks"
  on public.bookmarks for update to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

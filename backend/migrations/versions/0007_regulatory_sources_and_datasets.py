"""Regulatory sources, reference datasets and dataset versions (R1-050).

Revision ID: 0007
Revises: 0006

Platform-level tables: no tenant_id, read-only to tenant users. Law is data (CLAUDE.md rule 1),
so what may drive a decision is decided here, in the database, and not in application code:

- a dataset version is loaded `pending`; only a domain owner can make it `active` or `retired`;
- a loaded version's content is immutable; a new version is a new row;
- a source may be registered `draft` or `laid` by the loader; `in_force`/`commenced` are
  set by a domain owner only;
- only platform-mode sessions (loader, platform API) can write these tables at all.

Residual risk (docs/SECURITY.md): "domain owner" is decided from `app.user_id`, which the
application sets. Anyone holding the `cbam_app` database credentials can set it, exactly as
they could set `app.tenant_id` for tenant RLS. A separate approver credential is an open item.
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_SQL = """
create extension if not exists btree_gist;

create table cbam.platform_domain_owners (
  user_id uuid primary key references cbam.users (id),
  created_at timestamptz not null default now(),
  created_by uuid
);
alter table cbam.platform_domain_owners enable row level security;
alter table cbam.platform_domain_owners force row level security;
-- A user may check whether they themselves are a domain owner.
create policy domain_owner_self on cbam.platform_domain_owners for select
  using (user_id = cbam.current_user_id() or cbam.is_platform());
-- Granting the role is an operator action on the database (not an application path).
create policy domain_owner_granted on cbam.platform_domain_owners for insert
  with check (cbam.is_platform());
create policy domain_owner_revoked on cbam.platform_domain_owners for delete
  using (cbam.is_platform());
revoke insert, update, delete, truncate on cbam.platform_domain_owners from cbam_app;

create function cbam.is_domain_owner() returns boolean language sql stable as
$$ select exists (select 1 from cbam.platform_domain_owners
                  where user_id = cbam.current_user_id()) $$;

create table cbam.regulatory_sources (
  id uuid primary key,
  source_id text not null unique check (source_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]*$'),
  title text not null check (length(btrim(title)) > 0),
  source_type text not null
    check (source_type in ('legislation','regulation','notice','system_boundary','guidance')),
  url text,
  publication_date date,
  status text not null check (status in ('draft','laid','in_force','commenced','superseded')),
  commencement_date date,
  effective_from date,
  effective_to date,
  retrieved_at timestamptz,
  checksum_sha256 text check (checksum_sha256 ~ '^[0-9a-f]{64}$'),
  supersedes_source_id uuid references cbam.regulatory_sources (id),
  notes text,
  created_at timestamptz not null default now(),
  created_by uuid,
  updated_at timestamptz,
  row_version integer not null default 1,
  check (effective_to is null or effective_from is null or effective_to > effective_from)
);

create table cbam.ref_datasets (
  id uuid primary key,
  name text not null unique check (name ~ '^[a-z][a-z0-9_]*$'),
  created_at timestamptz not null default now()
);

create table cbam.ref_dataset_versions (
  id uuid primary key,
  dataset_id uuid not null references cbam.ref_datasets (id),
  version text not null check (length(btrim(version)) > 0),
  source_id uuid not null references cbam.regulatory_sources (id),
  checksum_sha256 text not null check (checksum_sha256 ~ '^[0-9a-f]{64}$'),
  effective_from date not null,
  effective_to date,
  is_fixture boolean not null default false,
  row_count integer not null check (row_count >= 0),
  status text not null default 'pending' check (status in ('pending','active','retired')),
  loaded_at timestamptz not null,
  loaded_by uuid,
  activated_by uuid,
  activated_at timestamptz,
  retired_at timestamptz,
  impact_report jsonb,
  notes text,
  updated_at timestamptz,
  row_version integer not null default 1,
  unique (dataset_id, version),
  check (effective_to is null or effective_to > effective_from)
);
-- At most one active version per dataset, checked at commit: activation first makes the new
-- version active (its guard compares the impact report with the version active right then), and
-- then retires the previous one in the same transaction.
alter table cbam.ref_dataset_versions add constraint ref_one_active_version
  exclude using gist (dataset_id with =) where (status = 'active') deferrable initially deferred;

create function cbam.ref_sources_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'regulatory sources are never deleted';
  end if;
  if tg_op = 'INSERT' then
    if new.status not in ('draft','laid') and not cbam.is_domain_owner() then
      raise exception 'only a domain owner can register a source as %', new.status
        using errcode = '42501';
    end if;
    return new;
  end if;
  if not cbam.is_domain_owner() then
    raise exception 'only a domain owner can change a regulatory source'
      using errcode = '42501';
  end if;
  if new.source_id is distinct from old.source_id then
    raise exception 'a source identifier cannot change';
  end if;
  if new.status is not distinct from old.status then
    if (new.commencement_date, new.effective_from, new.effective_to, new.title, new.source_type,
        new.url, new.publication_date, new.supersedes_source_id)
       is distinct from
       (old.commencement_date, old.effective_from, old.effective_to, old.title, old.source_type,
        old.url, old.publication_date, old.supersedes_source_id) then
      raise exception 'a source changes only together with its status';
    end if;
    return new;
  end if;
  -- One way (CLAUDE.md rule 17): a source is never moved back, and only a source that was in
  -- force is superseded, with the date it stops applying so earlier dates still replay.
  if not ((old.status = 'draft' and new.status in ('laid','in_force','commenced'))
          or (old.status = 'laid' and new.status in ('in_force','commenced'))
          or (old.status in ('in_force','commenced') and new.status = 'superseded')) then
    raise exception 'source status cannot go from % to %', old.status, new.status;
  end if;
  if new.status = 'superseded' and new.effective_to is null then
    raise exception 'a superseded source needs the date it stopped applying';
  end if;
  return new;
end $$;
create trigger ref_sources_guard before insert or update or delete on cbam.regulatory_sources
  for each row execute function cbam.ref_sources_guard();

create function cbam.ref_versions_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'reference dataset versions are never deleted';
  end if;
  if tg_op = 'INSERT' then
    if new.status <> 'pending' then
      raise exception 'a dataset version is always loaded as pending';
    end if;
    return new;
  end if;
  if (new.id, new.dataset_id, new.version, new.source_id, new.checksum_sha256,
      new.effective_from, new.effective_to, new.is_fixture, new.row_count,
      new.loaded_at, new.loaded_by)
     is distinct from
     (old.id, old.dataset_id, old.version, old.source_id, old.checksum_sha256,
      old.effective_from, old.effective_to, old.is_fixture, old.row_count,
      old.loaded_at, old.loaded_by) then
    raise exception 'a loaded dataset version is immutable; load a new version instead';
  end if;
  if new.status is not distinct from old.status then
    if (new.activated_by, new.activated_at, new.retired_at)
       is distinct from (old.activated_by, old.activated_at, old.retired_at) then
      raise exception 'activation fields change only with the status';
    end if;
    if new.impact_report is distinct from old.impact_report then
      if old.status <> 'pending' then
        raise exception 'the impact report of a % version is fixed', old.status;
      end if;
      if not cbam.is_domain_owner() then
        raise exception 'only a domain owner can record an impact report'
          using errcode = '42501';
      end if;
    end if;
    return new;
  end if;
  if not ((old.status = 'pending' and new.status in ('active','retired'))
          or (old.status = 'active' and new.status = 'retired')) then
    raise exception 'dataset version status cannot go from % to %', old.status, new.status;
  end if;
  if not cbam.is_domain_owner() then
    raise exception 'only a domain owner can change the status of a dataset version'
      using errcode = '42501';
  end if;
  if new.status = 'active' then
    if new.activated_by is distinct from cbam.current_user_id() or new.activated_at is null then
      raise exception 'activation must record who approved it and when';
    end if;
    if new.row_count = 0 then
      raise exception 'an empty dataset version cannot be activated';
    end if;
    -- The report must be for this very version and compared with what is active right now.
    if new.impact_report is null
       or new.impact_report ->> 'version_id' is distinct from new.id::text
       or new.impact_report ->> 'checksum_sha256' is distinct from new.checksum_sha256
       or (new.impact_report -> 'compared_to' ->> 'id') is distinct from
          (select v.id::text from cbam.ref_dataset_versions v
            where v.dataset_id = new.dataset_id and v.status = 'active' and v.id <> new.id) then
      raise exception 'activation needs a current impact report for this version';
    end if;
  end if;
  if new.status = 'retired' and new.retired_at is null then
    raise exception 'retirement must record when';
  end if;
  return new;
end $$;
create trigger ref_versions_guard before insert or update or delete on cbam.ref_dataset_versions
  for each row execute function cbam.ref_versions_guard();

-- Data rows exist only inside a pending version and never change afterwards.
create function cbam.ref_data_guard() returns trigger language plpgsql as $$
declare
  version_status text;
  sealed boolean;
begin
  if tg_op <> 'INSERT' then
    raise exception 'reference data rows are immutable; load a new dataset version instead';
  end if;
  select status, impact_report is not null into version_status, sealed
    from cbam.ref_dataset_versions where id = new.dataset_version_id;
  if version_status is distinct from 'pending' then
    raise exception 'rows can only be added to a pending dataset version';
  end if;
  if sealed then
    raise exception 'rows cannot be added after the impact report was made';
  end if;
  return new;
end $$;

revoke delete, truncate on cbam.regulatory_sources, cbam.ref_datasets,
  cbam.ref_dataset_versions from cbam_app;

-- Platform-level tables carry no tenant, but every cbam table has forced row-level security
-- (a test enforces it). Anyone may read; only platform-mode sessions (loader, platform API) may
-- write, and the triggers above and the grants decide what those writes may do.
alter table cbam.regulatory_sources enable row level security;
alter table cbam.regulatory_sources force row level security;
create policy open_read on cbam.regulatory_sources for select using (true);
create policy platform_insert on cbam.regulatory_sources for insert
  with check (cbam.is_platform());
create policy platform_update on cbam.regulatory_sources for update
  using (cbam.is_platform()) with check (cbam.is_platform());
alter table cbam.ref_datasets enable row level security;
alter table cbam.ref_datasets force row level security;
create policy open_read on cbam.ref_datasets for select using (true);
create policy platform_insert on cbam.ref_datasets for insert
  with check (cbam.is_platform());
alter table cbam.ref_dataset_versions enable row level security;
alter table cbam.ref_dataset_versions force row level security;
create policy open_read on cbam.ref_dataset_versions for select using (true);
create policy platform_insert on cbam.ref_dataset_versions for insert
  with check (cbam.is_platform());
create policy platform_update on cbam.ref_dataset_versions for update
  using (cbam.is_platform()) with check (cbam.is_platform());
"""


def upgrade() -> None:
    op.execute("set local role cbam_owner")
    op.execute(_SQL)


def downgrade() -> None:
    op.execute("set local role cbam_owner")
    op.execute("drop table if exists cbam.ref_dataset_versions")
    op.execute("drop table if exists cbam.ref_datasets")
    op.execute("drop table if exists cbam.regulatory_sources")
    op.execute("drop function if exists cbam.ref_data_guard()")
    op.execute("drop function if exists cbam.ref_versions_guard()")
    op.execute("drop function if exists cbam.ref_sources_guard()")
    op.execute("drop table if exists cbam.platform_domain_owners")
    op.execute("drop function if exists cbam.is_domain_owner()")

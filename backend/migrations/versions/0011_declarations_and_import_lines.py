"""Parties, declarations, import lines and their lineage; the job lease owner (R1-005, R1-010).

Revision ID: 0011
Revises: 0010

Normalised customs facts, with lineage back to the raw row (CLAUDE.md rule 4). Every table is
append-only: UPDATE, DELETE and TRUNCATE are revoked from `cbam_app` and blocked by a trigger for
every role including the owner. A correction is a NEW version whose `supersedes_id` points at the
old one (unique, so a version has one successor); a trigger checks the chain.

None of these tables holds a tax point, scope, quarter or threshold: `acceptance_date` is the date
the report gave and is NOT a tax point (CLAUDE.md rule 3; that is Phase 4). Customs value is kept
as declared (`customs_value_source` + currency); `customs_value_gbp` is only set when the currency
is GBP (no FX here: R1-035 is Phase 10). `value_source` records how the value was derived
(R1-010); anything other than `declared` must carry a `value_override_reason`.

`cbam.impact_line_counts_by_code_prefix` is the platform's first cross-tenant code path: a
SECURITY DEFINER function that returns COUNTS of current lines per prefix and tenant, nothing
else, and only in platform mode. It is owned by the NOLOGIN role `cbam_impact_reader`, which can
only SELECT `import_lines` (through a policy for that role alone); the table owner and `cbam_app`
get no such policy. The role is created NOLOGIN NOINHERIT NOBYPASSRLS (and corrected if it
already exists). The table owner is made a member only while the migration (or its downgrade)
hands the function over or drops it, and the membership is revoked again, so no other role can
SET ROLE into the reader. The role itself is cluster-level and, like the roles of 0001, is not
dropped by the downgrade (so the upgrade is repeatable).

`import_batches.lease_owner` is the token of the job holding the lease: only that job may renew
or release it.
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_TABLES = ("parties", "declarations", "import_lines", "import_line_sources")

_SQL = """
alter table cbam.import_batches add column lease_owner uuid;
-- Used by the ledger's has_open_exceptions filter and the line detail.
create index row_exceptions_source_row on cbam.row_exceptions (tenant_id, source_row_id);

create function cbam.import_facts_block_change() returns trigger language plpgsql as $$
begin
  raise exception 'normalised import facts are append-only: a correction is a new version';
end $$;

create table cbam.parties (
  id uuid primary key,
  tenant_id uuid not null references cbam.tenants (id),
  eori text check (eori ~ '^(GB|XI)[0-9]{12}$'),
  name text check (length(name) <= 500),        -- a business name can be personal data: never logged
  created_at timestamptz not null default now(),
  unique (tenant_id, id)
);
create unique index parties_tenant_eori on cbam.parties (tenant_id, eori) where eori is not null;

create table cbam.declarations (
  id uuid primary key,
  tenant_id uuid not null references cbam.tenants (id),
  mrn text not null check (length(mrn) between 1 and 100),
  version integer not null check (version >= 1),
  supersedes_id uuid,
  acceptance_date date not null,               -- as the report gave it: NOT a tax point
  acceptance_at timestamptz,
  procedure_code text check (length(procedure_code) <= 20),
  additional_procedure_codes text[],
  importer_party_id uuid,
  declarant_party_id uuid,
  representative_party_id uuid,
  representation_type text not null default 'unknown'
    check (representation_type in ('self','direct','indirect','unknown')),
  eori_context text check (eori_context in ('GB','XI')),
  entry_method text not null check (entry_method in ('cds','gcd','manual','correction')),
  batch_id uuid not null,
  content_sha256 char(64) not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  hash_version integer not null default 1 check (hash_version in (1)),  -- rules.HASH_VERSION
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, mrn, version),
  unique (supersedes_id),
  check ((version = 1) = (supersedes_id is null)),
  foreign key (tenant_id, supersedes_id) references cbam.declarations (tenant_id, id),
  foreign key (tenant_id, importer_party_id) references cbam.parties (tenant_id, id),
  foreign key (tenant_id, declarant_party_id) references cbam.parties (tenant_id, id),
  foreign key (tenant_id, representative_party_id) references cbam.parties (tenant_id, id),
  foreign key (tenant_id, batch_id) references cbam.import_batches (tenant_id, id)
);
create index declarations_tenant_batch on cbam.declarations (tenant_id, batch_id);

create table cbam.import_lines (
  id uuid primary key,
  tenant_id uuid not null references cbam.tenants (id),
  declaration_id uuid not null,
  item_no integer not null check (item_no >= 1),
  version integer not null check (version >= 1),
  supersedes_id uuid,
  commodity_code text not null check (commodity_code ~ '^[0-9]{8,10}$'),  -- exactly as given
  description text check (length(description) <= 4096),
  net_mass_kg numeric(20,6) not null check (net_mass_kg >= 0),
  supplementary_qty numeric(20,6) check (supplementary_qty >= 0),
  supplementary_unit text check (length(supplementary_unit) <= 20),
  customs_value_source numeric(24,8) not null check (customs_value_source >= 0),
  customs_value_currency char(3) not null check (customs_value_currency ~ '^[A-Z]{3}$'),
  customs_value_gbp numeric(18,2) check (customs_value_gbp >= 0),   -- only when currency is GBP
  customs_value_gbp_note text check (customs_value_gbp_note ~ '^[a-z0-9_]{1,64}$'),
  fx_method text check (fx_method ~ '^[a-z0-9_]{1,64}$'),
  valuation_basis text check (length(valuation_basis) <= 200),      -- as declared, not interpreted
  value_source text not null default 'declared'
    check (value_source in ('declared','manual','correction')),
  value_override_reason text check (length(btrim(value_override_reason)) between 1 and 1000),
  country_of_origin_declared char(2) not null check (country_of_origin_declared ~ '^[A-Z]{2}$'),
  cpc text check (length(cpc) <= 20),
  batch_id uuid not null,
  source_row_id uuid not null,
  entry_method text not null check (entry_method in ('cds','gcd','manual','correction')),
  change_reason text check (change_reason ~ '^[a-z0-9_]{1,64}$'),
  content_sha256 char(64) not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  hash_version integer not null default 1 check (hash_version in (1)),
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, declaration_id, item_no, version),
  unique (supersedes_id),
  check ((version = 1) = (supersedes_id is null)),
  check (version = 1 or change_reason is not null),
  check (customs_value_gbp is null or customs_value_currency = 'GBP'),
  check (value_source = 'declared' or value_override_reason is not null),
  check (value_source <> 'correction' or supersedes_id is not null),
  check (entry_method <> 'correction' or supersedes_id is not null),
  foreign key (tenant_id, declaration_id) references cbam.declarations (tenant_id, id),
  foreign key (tenant_id, supersedes_id) references cbam.import_lines (tenant_id, id),
  foreign key (tenant_id, batch_id) references cbam.import_batches (tenant_id, id),
  foreign key (tenant_id, source_row_id) references cbam.source_rows (tenant_id, id)
);
create index import_lines_tenant_code on cbam.import_lines (tenant_id, commodity_code);
create index import_lines_tenant_declaration on cbam.import_lines (tenant_id, declaration_id);
create index import_lines_tenant_batch on cbam.import_lines (tenant_id, batch_id);

create table cbam.import_line_sources (
  id uuid primary key,
  tenant_id uuid not null references cbam.tenants (id),
  import_line_id uuid not null,
  source_row_id uuid not null,
  report_type text check (report_type in
    ('import_item','import_header','import_tax_lines','export_item')),
  role text not null check (role in ('primary','header','tax_line','duplicate_seen')),
  created_at timestamptz not null default now(),
  unique (import_line_id, source_row_id, role),
  foreign key (tenant_id, import_line_id) references cbam.import_lines (tenant_id, id),
  foreign key (tenant_id, source_row_id) references cbam.source_rows (tenant_id, id)
);
-- A row of an item report becomes at most one line, or is seen again as a duplicate of one.
create unique index import_line_sources_row_once on cbam.import_line_sources (source_row_id)
  where role in ('primary','duplicate_seen');
create index import_line_sources_line on cbam.import_line_sources (tenant_id, import_line_id);

-- The version chain is checked by the database as well as the application.
create function cbam.declarations_check_chain() returns trigger language plpgsql as $$
declare
  prev cbam.declarations%rowtype;
begin
  if new.supersedes_id is not null then
    select * into prev from cbam.declarations
     where tenant_id = new.tenant_id and id = new.supersedes_id;
    if not found or prev.mrn <> new.mrn or new.version <> prev.version + 1 then
      raise exception 'declaration version chain is broken';
    end if;
  end if;
  return new;
end $$;
create trigger declarations_chain before insert on cbam.declarations
  for each row execute function cbam.declarations_check_chain();

create function cbam.import_lines_check_chain() returns trigger language plpgsql as $$
declare
  prev cbam.import_lines%rowtype;
  prev_mrn text;
  new_mrn text;
begin
  if new.supersedes_id is not null then
    select * into prev from cbam.import_lines
     where tenant_id = new.tenant_id and id = new.supersedes_id;
    if not found or prev.item_no <> new.item_no or new.version <> prev.version + 1 then
      raise exception 'import line version chain is broken';
    end if;
    select mrn into prev_mrn from cbam.declarations
     where tenant_id = prev.tenant_id and id = prev.declaration_id;
    select mrn into new_mrn from cbam.declarations
     where tenant_id = new.tenant_id and id = new.declaration_id;
    if prev_mrn is distinct from new_mrn then
      raise exception 'a correction must stay on the same declaration reference';
    end if;
  end if;
  return new;
end $$;
create trigger import_lines_chain before insert on cbam.import_lines
  for each row execute function cbam.import_lines_check_chain();

create trigger parties_immutable before update or delete on cbam.parties
  for each row execute function cbam.import_facts_block_change();
create trigger declarations_immutable before update or delete on cbam.declarations
  for each row execute function cbam.import_facts_block_change();
create trigger import_lines_immutable before update or delete on cbam.import_lines
  for each row execute function cbam.import_facts_block_change();
create trigger import_line_sources_immutable before update or delete on cbam.import_line_sources
  for each row execute function cbam.import_facts_block_change();
create trigger parties_no_truncate before truncate on cbam.parties
  for each statement execute function cbam.import_facts_block_change();
create trigger declarations_no_truncate before truncate on cbam.declarations
  for each statement execute function cbam.import_facts_block_change();
create trigger import_lines_no_truncate before truncate on cbam.import_lines
  for each statement execute function cbam.import_facts_block_change();
create trigger import_line_sources_no_truncate before truncate on cbam.import_line_sources
  for each statement execute function cbam.import_facts_block_change();
"""

_RLS = "\n".join(
    f"""
alter table cbam.{t} enable row level security;
alter table cbam.{t} force row level security;
create policy tenant_isolation on cbam.{t}
  using (tenant_id = cbam.current_tenant()) with check (tenant_id = cbam.current_tenant());
revoke update, delete, truncate on cbam.{t} from cbam_app;
"""
    for t in _TABLES
)

_ROLE = """
do $$
begin
  if not exists (select from pg_roles where rolname = 'cbam_impact_reader') then
    create role cbam_impact_reader nologin noinherit nobypassrls;
  end if;
  -- Correct a pre-existing role too when this user is permitted to ...
  begin
    alter role cbam_impact_reader nologin noinherit nobypassrls nosuperuser nocreaterole
      nocreatedb noreplication;
  exception when insufficient_privilege then
    null;  -- ... and in every case check the result below.
  end;
  if exists (select from pg_roles where rolname = 'cbam_impact_reader'
             and (rolcanlogin or rolinherit or rolbypassrls or rolsuper or rolcreaterole
                  or rolcreatedb or rolreplication)) then
    raise exception 'role cbam_impact_reader has unsafe attributes and this user cannot fix them';
  end if;
end $$;
"""

# Needed only while the migration hands the function to the role (and while the downgrade drops
# it); the membership is revoked again so no other role can SET ROLE into the reader.
_GRANT_MEMBERSHIP = """
do $$
begin
  if not pg_has_role('cbam_owner', 'cbam_impact_reader', 'member') then
    grant cbam_impact_reader to cbam_owner;
  end if;
end $$;
"""

_REVOKE_MEMBERSHIP = """
do $$
declare
  g record;
  n integer;
begin
  for g in select pg_get_userbyid(m.grantor) as grantor from pg_auth_members m
            where m.roleid = 'cbam_impact_reader'::regrole and m.member = 'cbam_owner'::regrole
  loop
    begin
      execute format('revoke cbam_impact_reader from cbam_owner granted by %I', g.grantor);
    exception when others then
      null;  -- someone else's grant: checked below
    end;
  end loop;
  if pg_has_role('cbam_owner', 'cbam_impact_reader', 'member') then
    raise exception 'cbam_owner is still a member of cbam_impact_reader (granted by another '
      'role): remove that membership as a superuser or as the role that granted it';
  end if;
  -- Nobody may be able to SET ROLE into the reader or inherit it. ADMIN OPTION is allowed only
  -- for the migration user or a role that already controls roles (superuser or CREATEROLE).
  if current_setting('server_version_num')::int >= 160000 then
    execute
      'select count(*) from pg_auth_members m join pg_roles r on r.oid = m.member'
      ' where m.roleid = ''cbam_impact_reader''::regrole and (m.set_option or m.inherit_option'
      ' or (m.admin_option and r.rolname <> current_user and not (r.rolsuper or r.rolcreaterole)))'
      into n;
    if n > 0 then
      raise exception 'cbam_impact_reader has a member that can SET ROLE into it, inherit it or '
        'administer it';
    end if;
  end if;
end $$;
"""

_DEFINER = """
-- First cross-tenant code path (docs/SECURITY.md): counts only, current lines only. It runs as a
-- dedicated NOLOGIN role that can do nothing but read import_lines (and, through forced RLS, only
-- because of the policy below), not as the table owner.
grant usage on schema cbam to cbam_impact_reader;
grant create on schema cbam to cbam_impact_reader;
grant select on cbam.import_lines to cbam_impact_reader;
create policy impact_reader_select on cbam.import_lines for select to cbam_impact_reader
  using (true);

create function cbam.impact_line_counts_by_code_prefix(prefixes text[])
returns table (prefix text, tenant_id uuid, line_count bigint)
language plpgsql stable security definer set search_path = cbam, pg_temp as $$
begin
  if not cbam.is_platform() then
    raise exception 'impact counts are for platform reference-data work only';
  end if;
  if cardinality(prefixes) > 1000 then
    raise exception 'at most 1000 prefixes per call';
  end if;
  return query
    select p, l.tenant_id, count(*)::bigint
      from unnest(prefixes) as p
      join cbam.import_lines l
        on p ~ '^[0-9]{1,10}$' and left(l.commodity_code, length(p)) = p
     where not exists (select 1 from cbam.import_lines n
                        where n.tenant_id = l.tenant_id and n.supersedes_id = l.id)
     group by p, l.tenant_id;
end $$;
alter function cbam.impact_line_counts_by_code_prefix(text[]) owner to cbam_impact_reader;
revoke create on schema cbam from cbam_impact_reader;
revoke all on function cbam.impact_line_counts_by_code_prefix(text[]) from public;
grant execute on function cbam.impact_line_counts_by_code_prefix(text[]) to cbam_app;
"""

_DOWN = """
drop function cbam.impact_line_counts_by_code_prefix(text[]);
drop policy impact_reader_select on cbam.import_lines;
revoke select on cbam.import_lines from cbam_impact_reader;
revoke usage on schema cbam from cbam_impact_reader;
drop index cbam.row_exceptions_source_row;
drop table cbam.import_line_sources;
drop table cbam.import_lines;
drop table cbam.declarations;
drop table cbam.parties;
drop function cbam.import_lines_check_chain();
drop function cbam.declarations_check_chain();
drop function cbam.import_facts_block_change();
alter table cbam.import_batches drop column lease_owner;
"""


def upgrade() -> None:
    # Earlier migrations leave `set local role cbam_owner` in force inside one transaction.
    op.execute("reset role")
    op.execute(_ROLE)  # cluster-level, like the roles of 0001: created before acting as the owner
    op.execute(_GRANT_MEMBERSHIP)
    op.execute("set local role cbam_owner")
    op.execute(_SQL)
    op.execute(_RLS)
    op.execute(_DEFINER)
    op.execute("reset role")
    op.execute(_REVOKE_MEMBERSHIP)  # cbam_owner, cbam_app and the migration role cannot use it


def downgrade() -> None:
    op.execute("reset role")
    op.execute(_GRANT_MEMBERSHIP)  # the owner needs it to drop the function the role owns
    op.execute("set local role cbam_owner")
    op.execute(_DOWN)
    op.execute("reset role")
    op.execute(_REVOKE_MEMBERSHIP)

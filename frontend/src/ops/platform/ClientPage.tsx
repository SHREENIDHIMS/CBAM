import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import { Button } from '@/shared/components/ui/button'
import { Field, FormError } from '@/shared/components/AuthCard'
import type { Member, Tenant } from '@/shared/api/types'
import { ASSIGNABLE_ROLES, roleLabel } from '@/shared/roles'
import { describeError } from './errors'
import {
  useChangeTenantStatus,
  useInvite,
  useMembers,
  useRemoveMember,
  useSetRoles,
  useTenants,
} from './queries'

function RoleChoices(props: {
  legend: string
  selected: string[]
  onChange: (roles: string[]) => void
}) {
  return (
    <fieldset className="mb-4">
      <legend className="mb-1 text-sm font-medium">{props.legend}</legend>
      {ASSIGNABLE_ROLES.map((role) => {
        const id = `${props.legend}-${role.value}`
        return (
          <div key={role.value}>
            <input
              id={id}
              type="checkbox"
              checked={props.selected.includes(role.value)}
              onChange={(e) =>
                props.onChange(
                  e.target.checked
                    ? [...props.selected, role.value]
                    : props.selected.filter((r) => r !== role.value),
                )
              }
            />{' '}
            <label htmlFor={id}>{role.label}</label>
            {role.needsMfa && (
              <span className="text-sm text-neutral-600"> (needs two-step verification)</span>
            )}
          </div>
        )
      })}
    </fieldset>
  )
}

function StatusPanel({ tenant }: { tenant: Tenant }) {
  const change = useChangeTenantStatus(tenant)
  const [reason, setReason] = useState('')
  const options: { status: Tenant['status']; label: string }[] =
    tenant.status === 'active'
      ? [
          { status: 'suspended', label: 'Suspend' },
          { status: 'closed', label: 'Close permanently' },
        ]
      : tenant.status === 'suspended'
        ? [
            { status: 'active', label: 'Reactivate' },
            { status: 'closed', label: 'Close permanently' },
          ]
        : []

  return (
    <section aria-labelledby="status-heading" className="mb-8">
      <h2 id="status-heading" className="mb-2 text-lg font-semibold">
        Status: {tenant.status}
      </h2>
      {options.length === 0 ? (
        <p>This client is closed. Its records are kept; it cannot be reopened here.</p>
      ) : (
        <div className="max-w-md">
          <FormError message={change.isError ? describeError(change.error) : null} />
          <Field
            id="status-reason"
            label="Reason for the change"
            value={reason}
            onChange={setReason}
            required={false}
          />
          <div className="flex gap-2">
            {options.map((o) => (
              <Button
                key={o.status}
                variant="outline"
                disabled={reason.trim() === '' || change.isPending}
                onClick={() =>
                  change.mutate(
                    { status: o.status, reason: reason.trim() },
                    { onSuccess: () => setReason('') },
                  )
                }
              >
                {o.label}
              </Button>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

function MemberRow({ tenantId, member }: { tenantId: string; member: Member }) {
  const setRoles = useSetRoles(tenantId, member)
  const remove = useRemoveMember(tenantId)
  const [editing, setEditing] = useState(false)
  const [roles, setLocalRoles] = useState(member.roles)
  const [confirming, setConfirming] = useState(false)
  const error = setRoles.isError ? setRoles.error : remove.isError ? remove.error : null

  return (
    <tr className="border-t align-top">
      <td className="py-2">
        {member.email}
        {member.display_name && (
          <div className="text-sm text-neutral-600">{member.display_name}</div>
        )}
        {error && (
          <p role="alert" className="text-sm text-red-700">
            {describeError(error)}
          </p>
        )}
      </td>
      <td>
        {editing ? (
          <RoleChoices
            legend={`Roles for ${member.email}`}
            selected={roles}
            onChange={setLocalRoles}
          />
        ) : (
          member.roles.map(roleLabel).join(', ')
        )}
      </td>
      <td className="space-x-2">
        {editing ? (
          <>
            <Button
              size="sm"
              disabled={roles.length === 0 || setRoles.isPending}
              onClick={() => setRoles.mutate(roles, { onSuccess: () => setEditing(false) })}
            >
              Save roles<span className="sr-only"> for {member.email}</span>
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setEditing(false)
                setLocalRoles(member.roles)
              }}
            >
              Cancel
            </Button>
          </>
        ) : confirming ? (
          <>
            <Button
              size="sm"
              onClick={() => remove.mutate(member.user_id)}
              disabled={remove.isPending}
            >
              Yes, remove<span className="sr-only"> {member.email}</span>
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
              Keep
            </Button>
          </>
        ) : (
          <>
            <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
              Edit roles<span className="sr-only"> for {member.email}</span>
            </Button>
            <Button size="sm" variant="outline" onClick={() => setConfirming(true)}>
              Remove<span className="sr-only"> {member.email}</span>
            </Button>
          </>
        )}
      </td>
    </tr>
  )
}

function InviteForm({ tenantId }: { tenantId: string }) {
  const invite = useInvite(tenantId)
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [roles, setRoles] = useState<string[]>([])
  const [sentTo, setSentTo] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSentTo(null)
    try {
      const member = await invite.mutateAsync({
        email: email.trim(),
        roles,
        display_name: displayName.trim() || null,
      })
      setSentTo(member.email)
      setEmail('')
      setDisplayName('')
      setRoles([])
    } catch {
      // Shown from the mutation state.
    }
  }

  return (
    <form onSubmit={submit} className="max-w-md">
      <FormError message={invite.isError ? describeError(invite.error) : null} />
      {sentTo && (
        <p role="status" className="mb-4">
          Invitation sent to {sentTo}.
        </p>
      )}
      <Field
        id="invite-email"
        label="Email"
        type="email"
        autoComplete="off"
        value={email}
        onChange={setEmail}
      />
      <Field
        id="invite-name"
        label="Name (optional)"
        value={displayName}
        onChange={setDisplayName}
        required={false}
      />
      <RoleChoices legend="Roles" selected={roles} onChange={setRoles} />
      <Button type="submit" disabled={invite.isPending || roles.length === 0}>
        Send invitation
      </Button>
    </form>
  )
}

export function ClientPage() {
  const { tenantId = '' } = useParams()
  const tenants = useTenants()
  const members = useMembers(tenantId)
  const tenant = tenants.data?.find((t) => t.id === tenantId)

  if (tenants.isPending)
    return (
      <p role="status" className="p-6">
        Loading…
      </p>
    )
  if (!tenant) {
    return (
      <main className="p-6">
        <h1 className="text-2xl font-semibold">Not found</h1>
        <Link className="underline" to="/ops/platform">
          Back to clients
        </Link>
      </main>
    )
  }
  return (
    <main className="mx-auto max-w-3xl p-6">
      <p className="mb-2 text-sm">
        <Link className="underline" to="/ops/platform">
          All clients
        </Link>
      </p>
      <h1 className="mb-4 text-2xl font-semibold">{tenant.name}</h1>
      <StatusPanel key={tenant.row_version} tenant={tenant} />
      <h2 className="mb-2 text-lg font-semibold">People</h2>
      {members.isPending && <p role="status">Loading…</p>}
      {members.isError && <p role="alert">{describeError(members.error)}</p>}
      {members.data &&
        (members.data.length === 0 ? (
          <p className="mb-6">Nobody has access to this client yet.</p>
        ) : (
          <table className="mb-8 w-full text-left">
            <caption className="sr-only">People with access to {tenant.name}</caption>
            <thead>
              <tr>
                <th scope="col">Person</th>
                <th scope="col">Roles</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {members.data.map((m) => (
                <MemberRow
                  key={`${m.membership_id}-${m.row_version}`}
                  tenantId={tenantId}
                  member={m}
                />
              ))}
            </tbody>
          </table>
        ))}
      {tenant.status === 'active' ? (
        <>
          <h2 className="mb-2 text-lg font-semibold">Invite someone</h2>
          <InviteForm tenantId={tenantId} />
        </>
      ) : (
        <p>People can only be invited to an active client.</p>
      )}
    </main>
  )
}

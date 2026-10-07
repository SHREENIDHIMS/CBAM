import { useState, type FormEvent } from 'react'
import { Link, useOutletContext, useParams } from 'react-router'
import type { Membership } from '@/shared/api/types'
import { Button } from '@/shared/components/ui/button'
import { isRealDate } from '../imports/filters'
import { safeDate, statusLabel } from '../imports/format'
import { Shell } from '../imports/Shell'
import { describeError } from '../platform/errors'
import { useEoris, useRegisterEori, useScan, useUpdateEori } from './queries'
import { ACCESS_VALUES, EORI_PATTERN, NOTE_MAX, type Eori, type ThirdPartyAccess } from './types'

const inputCls = 'rounded-md border border-input px-2 py-1'
const HOME = { to: '', label: 'Back to home' }

function FieldError({ id, message }: { id: string; message?: string }) {
  return message ? (
    <span id={id} role="alert" className="block text-sm">
      {message}
    </span>
  ) : null
}

function AccessSelect({
  id,
  value,
  onChange,
}: {
  id: string
  value: ThirdPartyAccess
  onChange: (v: ThirdPartyAccess) => void
}) {
  return (
    <select
      id={id}
      className={inputCls}
      value={value}
      onChange={(e) => onChange(e.target.value as ThirdPartyAccess)}
    >
      {ACCESS_VALUES.map((a) => (
        <option key={a} value={a}>
          {a}
        </option>
      ))}
    </select>
  )
}

function RegisterForm({ tenantId }: { tenantId: string }) {
  const register = useRegisterEori(tenantId)
  const [eori, setEori] = useState('')
  const [from, setFrom] = useState('')
  const [access, setAccess] = useState<ThirdPartyAccess>('unknown')
  const [note, setNote] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})

  async function submit(event: FormEvent) {
    event.preventDefault()
    const found: Record<string, string> = {}
    if (!EORI_PATTERN.test(eori)) found.eori = 'EORI must be GB or XI followed by 12 digits.'
    if (!isRealDate(from)) found.from = 'Enter the first day to cover as a real date.'
    if (note.length > NOTE_MAX) found.note = `Note can be at most ${NOTE_MAX} characters.`
    setErrors(found)
    if (Object.keys(found).length > 0) return
    try {
      await register.mutateAsync({
        eori,
        tracking_from: from,
        third_party_access: access,
        note: note.trim() === '' ? null : note.trim(),
      })
      setEori('')
      setFrom('')
      setAccess('unknown')
      setNote('')
    } catch {
      // Shown from the mutation state below.
    }
  }

  const aria = (key: string) =>
    errors[key] ? { 'aria-invalid': true, 'aria-describedby': `err-${key}` } : {}
  return (
    <form onSubmit={submit} noValidate className="mb-8 max-w-xl" aria-labelledby="register-h">
      <h2 id="register-h" className="mb-2 text-lg font-semibold">
        Register an EORI
      </h2>
      {register.isError && <p role="alert">{describeError(register.error)}</p>}
      <div className="mb-3">
        <label htmlFor="r-eori" className="block text-sm font-medium">
          EORI
        </label>
        <input
          id="r-eori"
          className={inputCls}
          value={eori}
          onChange={(e) => setEori(e.target.value.trim().toUpperCase())}
          {...aria('eori')}
        />
        <FieldError id="err-eori" message={errors.eori} />
      </div>
      <div className="mb-3">
        <label htmlFor="r-from" className="block text-sm font-medium">
          First day to cover
        </label>
        <input
          id="r-from"
          type="date"
          className={inputCls}
          value={from}
          onChange={(e) => setFrom(e.target.value)}
          {...aria('from')}
        />
        <FieldError id="err-from" message={errors.from} />
      </div>
      <div className="mb-3">
        <label htmlFor="r-access" className="block text-sm font-medium">
          Third-party access
        </label>
        <AccessSelect id="r-access" value={access} onChange={setAccess} />
      </div>
      <div className="mb-3">
        <label htmlFor="r-note" className="block text-sm font-medium">
          Note (optional)
        </label>
        <textarea
          id="r-note"
          className={`${inputCls} w-full`}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          {...aria('note')}
        />
        <FieldError id="err-note" message={errors.note} />
      </div>
      <Button type="submit" disabled={register.isPending}>
        Register EORI
      </Button>
    </form>
  )
}

function EditForm({ tenantId, row, onClose }: { tenantId: string; row: Eori; onClose: () => void }) {
  const update = useUpdateEori(tenantId, row)
  const [access, setAccess] = useState(row.third_party_access)
  const [note, setNote] = useState(row.note ?? '')
  const [error, setError] = useState<string | null>(null)
  const changedAccess = access !== row.third_party_access
  const changedNote = note.trim() !== (row.note ?? '')

  async function save(event: FormEvent) {
    event.preventDefault()
    if (note.length > NOTE_MAX) return setError(`Note can be at most ${NOTE_MAX} characters.`)
    setError(null)
    try {
      await update.mutateAsync({
        ...(changedAccess ? { third_party_access: access } : {}),
        ...(changedNote ? { note: note.trim() === '' ? null : note.trim() } : {}),
      })
      onClose()
    } catch {
      // Shown from the mutation state below.
    }
  }

  return (
    <form onSubmit={save} aria-label={`Edit ${row.eori}`} className="my-2 max-w-xl rounded border p-3">
      {(error || update.isError) && <p role="alert">{error ?? describeError(update.error)}</p>}
      <p className="mb-2 text-sm">
        First day to cover ({safeDate(row.tracking_from)}) cannot be changed.
      </p>
      <div className="mb-2">
        <label htmlFor={`e-access-${row.id}`} className="block text-sm font-medium">
          Third-party access for {row.eori}
        </label>
        <AccessSelect id={`e-access-${row.id}`} value={access} onChange={setAccess} />
      </div>
      <div className="mb-2">
        <label htmlFor={`e-note-${row.id}`} className="block text-sm font-medium">
          Note for {row.eori}
        </label>
        <textarea
          id={`e-note-${row.id}`}
          className={`${inputCls} w-full`}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </div>
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={update.isPending || !(changedAccess || changedNote)}>
          Save changes
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

function ScanBox({ tenantId }: { tenantId: string }) {
  const scan = useScan(tenantId)
  return (
    <div className="mb-8">
      <Button variant="outline" disabled={scan.isPending} onClick={() => scan.mutate()}>
        {scan.isPending ? 'Checking…' : 'Check for gaps now'}
      </Button>
      {scan.isError && <p role="alert">{describeError(scan.error)}</p>}
      {scan.data && (
        <p role="status" className="mt-2">
          Checked {scan.data.eoris_scanned} EORI(s). New gap tasks: {scan.data.gap_tasks_created}.
          New monthly tasks: {scan.data.month_tasks_created}.
        </p>
      )}
    </div>
  )
}

export function EoriRegisterPage() {
  const { tenantId = '' } = useParams()
  const { membership } = useOutletContext<{ membership: Membership }>()
  const canWrite = membership.permissions.includes('imports:write')
  const eoris = useEoris(tenantId)
  const [editing, setEditing] = useState<string | null>(null)

  return (
    <Shell tenantId={tenantId} title="Customs data coverage" back={HOME}>
      <p className="mb-4 text-sm">
        This shows which days of customs data have been loaded for each EORI. It is coverage only,
        not a threshold or tax point decision.
      </p>
      {eoris.isPending && <p role="status">Loading…</p>}
      {eoris.isError && <p role="alert">{describeError(eoris.error)}</p>}
      {eoris.data && eoris.data.length === 0 && <p className="mb-6">No EORIs registered yet.</p>}
      {eoris.data && eoris.data.length > 0 && (
        <table className="mb-6 w-full text-left">
          <caption className="sr-only">Registered EORIs</caption>
          <thead>
            <tr>
              <th scope="col">EORI</th>
              <th scope="col">First day to cover</th>
              <th scope="col">Third-party access</th>
              <th scope="col">Note</th>
              <th scope="col">Row version</th>
              {canWrite && <th scope="col">Actions</th>}
            </tr>
          </thead>
          <tbody>
            {eoris.data.map((r) => (
              <tr key={r.id} className="border-t align-top">
                <td className="py-1">
                  <Link
                    className="underline"
                    to={`/ops/t/${encodeURIComponent(tenantId)}/customs-data/${encodeURIComponent(r.eori)}`}
                  >
                    {r.eori}
                  </Link>
                </td>
                <td>{safeDate(r.tracking_from)}</td>
                <td>
                  {statusLabel(r.third_party_access)}
                  {r.access_recorded_on && ` (recorded ${safeDate(r.access_recorded_on)})`}
                </td>
                <td className="whitespace-pre-wrap break-words">{r.note ?? '—'}</td>
                <td>{r.row_version}</td>
                {canWrite && (
                  <td>
                    <Button
                      size="sm"
                      variant="outline"
                      aria-label={`Edit access / note for ${r.eori}`}
                      onClick={() => setEditing(editing === r.id ? null : r.id)}
                    >
                      Edit access / note
                    </Button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {canWrite && eoris.data?.map(
        (r) =>
          editing === r.id && (
            <EditForm
              key={`${r.id}-${r.row_version}`}
              tenantId={tenantId}
              row={r}
              onClose={() => setEditing(null)}
            />
          ),
      )}
      {canWrite && <ScanBox tenantId={tenantId} />}
      {canWrite && <RegisterForm tenantId={tenantId} />}
    </Shell>
  )
}

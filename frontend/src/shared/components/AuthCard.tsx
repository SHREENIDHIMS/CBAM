import type { ReactNode } from 'react'

export function AuthCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="mx-auto max-w-md p-6">
      <h1 className="mb-4 text-2xl font-semibold">{title}</h1>
      {children}
    </main>
  )
}

export function Field(props: {
  id: string
  label: string
  type?: string
  value: string
  onChange: (value: string) => void
  autoComplete?: string
  inputMode?: 'numeric'
  required?: boolean
}) {
  return (
    <div className="mb-4">
      <label htmlFor={props.id} className="mb-1 block text-sm font-medium">
        {props.label}
      </label>
      <input
        id={props.id}
        type={props.type ?? 'text'}
        value={props.value}
        required={props.required ?? true}
        autoComplete={props.autoComplete}
        inputMode={props.inputMode}
        onChange={(e) => props.onChange(e.target.value)}
        className="w-full rounded-md border border-input px-3 py-2"
      />
    </div>
  )
}

export function FormError({ message }: { message: string | null }) {
  return message ? (
    <p role="alert" className="mb-4 text-sm text-red-700">
      {message}
    </p>
  ) : null
}

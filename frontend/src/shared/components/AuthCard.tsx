import type { ReactNode } from 'react'

export function AuthCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="auth-page">
      <div className="auth-brand-panel">
        <div className="brand-mark">C</div>
        <p className="eyebrow">CBAM CONTROL ROOM</p>
        <h2>Evidence you can defend.</h2>
        <p>Track customs data, reference sources and coverage decisions in one controlled workspace.</p>
      </div>
      <section className="auth-card" aria-labelledby="auth-title">
        <p className="eyebrow text-emerald-700">SECURE ACCESS</p>
        <h1 id="auth-title">{title}</h1>
        {children}
      </section>
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
        className="app-input"
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

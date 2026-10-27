import type { ButtonHTMLAttributes } from 'react'

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'default' | 'outline' | 'ghost' | 'danger'
  size?: 'default' | 'sm' | 'lg'
}

export function Button({
  className = '',
  variant = 'default',
  size = 'default',
  ...props
}: ButtonProps) {
  return (
    <button
      className={`app-button app-button-${variant} app-button-${size} ${className}`.trim()}
      {...props}
    />
  )
}

import type { ButtonHTMLAttributes } from 'react'

type Variant = 'primary' | 'secondary' | 'quiet'

// Primary is the one yellow action on a screen ("yellow means act here").
const VARIANTS: Record<Variant, string> = {
  primary: 'bg-marking text-asphalt hover:bg-[#e2b500] font-semibold',
  secondary: 'bg-kerb text-asphalt border border-asphalt hover:bg-concrete font-medium',
  quiet: 'text-asphalt underline underline-offset-4 decoration-hairline hover:decoration-asphalt font-medium',
}

export const buttonClass = (variant: Variant = 'secondary', extra = '') =>
  `inline-flex min-h-11 items-center justify-center gap-2 rounded px-4 text-base disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${extra}`

export function Button({
  variant = 'secondary',
  className = '',
  type = 'button',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return <button type={type} className={buttonClass(variant, className)} {...props} />
}

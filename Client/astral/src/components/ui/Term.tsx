import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'

type TermKey = 'ADT' | 'SLA' | 'PBT'

/** Jargon with a plain-language definition on hover, focus or tap (spec §9.2 Language, T8.6). */
export function Term({ name, children }: { name: TermKey; children?: string }) {
  const { t } = useTranslation()
  const id = useId()
  const [open, setOpen] = useState(false)
  return (
    <span className="relative inline-block">
      <button type="button" aria-describedby={open ? id : undefined} aria-expanded={open}
        onClick={() => setOpen((o) => !o)} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
        onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
        className="cursor-help underline decoration-dotted underline-offset-4">
        {children ?? name}
      </button>
      {open && (
        <span id={id} role="tooltip"
          className="absolute top-full left-0 z-[1600] mt-1 w-64 rounded bg-asphalt px-3 py-2 text-left text-sm font-normal text-kerb shadow-lg">
          {t(`term.${name}`)}
        </span>
      )}
    </span>
  )
}

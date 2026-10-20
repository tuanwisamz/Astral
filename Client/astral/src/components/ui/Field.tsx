import { useId, type InputHTMLAttributes } from 'react'

/** Label above, hint or error below. Errors replace the hint so there's one message at a time. */
export function Field({
  label,
  hint,
  error,
  ...input
}: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string; error?: string }) {
  const id = useId()
  const noteId = `${id}-note`
  const note = error ?? hint
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-sm font-medium">{label}</label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={note ? noteId : undefined}
        className={`block min-h-11 w-full rounded border bg-kerb px-3 text-base ${
          error ? 'border-overdue' : 'border-road'
        }`}
        {...input}
      />
      {note && (
        <p id={noteId} className={`text-sm ${error ? 'text-overdue' : 'text-road'}`}>{note}</p>
      )}
    </div>
  )
}

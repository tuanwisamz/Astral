import { useTranslation } from 'react-i18next'

import type { AuthState } from '../../app/auth'

type Role = AuthState['role']

// Admin is filled so it stands out; other staff get an outline; reporters stay quiet. No yellow:
// marking yellow is reserved for the one action on a screen (DESIGN.md).
const STYLES: Record<Role, string> = {
  admin: 'border-asphalt bg-asphalt text-kerb',
  officer: 'border-asphalt text-asphalt',
  viewer: 'border-road text-road',
  public: 'border-hairline text-road',
  dev: 'border-dashed border-road text-road',
}

/** The account's role (U2), shown in the top bar beside the language toggle and email. */
export function RoleBadge({ role }: { role: Role }) {
  const { t } = useTranslation()
  const full = role === 'dev' ? t('app.devMode') : t(`admin.roles.${role}`)
  return (
    <span title={full}
      className={`inline-flex min-h-6 shrink-0 items-center rounded-[3px] border px-1.5 text-xs font-semibold ${STYLES[role]}`}>
      <span className="sr-only">{t('roles.label')} </span>
      {t(`roles.short.${role}`)}
    </span>
  )
}

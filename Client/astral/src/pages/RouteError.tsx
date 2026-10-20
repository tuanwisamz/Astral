import { useTranslation } from 'react-i18next'
import { isRouteErrorResponse, Link, useRouteError } from 'react-router'

import { buttonClass } from '../components/ui/Button'
import { EmptyState } from '../components/ui/Status'

/** Replaces React Router's developer error page with one in the product's voice. */
export default function RouteError() {
  const { t } = useTranslation()
  const error = useRouteError()
  const notFound = isRouteErrorResponse(error) && error.status === 404
  if (!notFound) console.error(error)
  return (
    <div className="px-6 sm:px-12">
      <EmptyState
        title={t(notFound ? 'errorPage.notFoundTitle' : 'errorPage.crashTitle')}
        body={t(notFound ? 'errorPage.notFoundBody' : 'errorPage.crashBody')}
        action={<Link to="/" reloadDocument className={buttonClass('secondary')}>{t('errorPage.home')}</Link>}
      />
    </div>
  )
}

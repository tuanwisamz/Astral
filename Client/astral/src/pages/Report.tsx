import 'leaflet/dist/leaflet.css'

import { useMutation, useQuery } from '@tanstack/react-query'
import L from 'leaflet'
import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Circle, MapContainer, Marker, TileLayer, useMap } from 'react-leaflet'

import { useApi, useAuthState } from '../app/auth'
import { CameraCapture } from '../components/report/CameraCapture'
import { Button, buttonClass } from '../components/ui/Button'
import { Field } from '../components/ui/Field'
import { HazardIcon } from '../components/ui/HazardIcon'
import { RoutePlate } from '../components/ui/RoutePlate'
import { ErrorBox } from '../components/ui/Status'
import { ApiError, errorVars } from '../lib/api'
import { formatDateTime, formatRelative } from '../lib/format'
import { HAZARD_TYPES, HAZARDS, type HazardType } from '../lib/hazards'
import type { PhotoAnalysis, ReportResult } from '../lib/types'

const TILE_URL: string = import.meta.env.VITE_MAP_TILE_URL ?? 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
type Step = 'photo' | 'location' | 'details' | 'done'

// Camera-only reports (U3): the same limits the server checks in api/v1/reports.py.
const MAX_GPS_ACCURACY_M = 100
const MAX_PIN_SHIFT_M = 100
const LOCATION_ERRORS = ['NOT_ON_ROAD', 'OUTSIDE_COVERAGE', 'PIN_TOO_FAR']
const RETAKE_ERRORS = ['GPS_TOO_COARSE', 'CAPTURE_EXPIRED']

interface Fix {
  lat: number
  lng: number
  accuracy: number
  at: number
}

interface Shot {
  file: File
  url: string
  token: string
  /** Where the phone was when the shutter was pressed. */
  fix: Fix
  takenAt: string
}

type GpsStatus = 'waiting' | 'ok' | 'coarse' | 'denied' | 'unavailable'

const pin = L.divIcon({
  className: 'hazard-marker',
  html: '<svg width="34" height="44" viewBox="0 0 34 44" aria-hidden="true"><path d="M17 43s15-15.6 15-26A15 15 0 0 0 2 17c0 10.4 15 26 15 26z" fill="#2E3236" stroke="#fff" stroke-width="2"/><circle cx="17" cy="17" r="6" fill="#F5C400"/></svg>',
  iconSize: [34, 44],
  iconAnchor: [17, 43],
})

function metresBetween(a: [number, number], b: [number, number]): number {
  const rad = Math.PI / 180
  const dLat = (b[0] - a[0]) * rad
  const dLng = (b[1] - a[1]) * rad
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * rad) * Math.cos(b[0] * rad) * Math.sin(dLng / 2) ** 2
  return 2 * 6_371_000 * Math.asin(Math.sqrt(h))
}

/** Keeps the pin within MAX_PIN_SHIFT_M of the fix by pulling it back to the edge of the circle. */
function clampToCircle(fix: Fix, p: [number, number]): [number, number] {
  const d = metresBetween([fix.lat, fix.lng], p)
  if (d <= MAX_PIN_SHIFT_M) return p
  const k = (MAX_PIN_SHIFT_M * 0.98) / d
  return [fix.lat + (p[0] - fix.lat) * k, fix.lng + (p[1] - fix.lng) * k]
}

/** The phone's GPS while the camera is open: the sharpest recent fix wins. */
function useGpsFix(): { status: GpsStatus; fix: Fix | null } {
  const supported = 'geolocation' in navigator
  const [fix, setFix] = useState<Fix | null>(null)
  const [error, setError] = useState<'denied' | 'unavailable' | null>(null)
  useEffect(() => {
    if (!supported) return
    const id = navigator.geolocation.watchPosition(
      (p) => {
        const next = { lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy, at: p.timestamp }
        setError(null)
        // Keep the sharper of the last fix and this one, unless the last is over 30 s old.
        setFix((last) => (last && last.accuracy < next.accuracy && next.at - last.at < 30_000 ? last : next))
      },
      (err) => setError(err.code === err.PERMISSION_DENIED ? 'denied' : 'unavailable'),
      { enableHighAccuracy: true, maximumAge: 0, timeout: 20_000 },
    )
    return () => navigator.geolocation.clearWatch(id)
  }, [supported])
  if (!supported) return { status: 'unavailable', fix: null }
  if (fix) return { status: fix.accuracy <= MAX_GPS_ACCURACY_M ? 'ok' : 'coarse', fix }
  return { status: error ?? 'waiting', fix: null }
}

function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setSettled(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return settled
}

function Recentre({ at }: { at: [number, number] }) {
  const map = useMap()
  useEffect(() => {
    map.setView(at, Math.max(map.getZoom(), 17))
  }, [map, at])
  return null
}

function StepHeader({ n, title, body }: { n: number; title: string; body?: string }) {
  const { t } = useTranslation()
  return (
    <div className="mb-5">
      <p className="text-sm text-road">{t('report.step', { n, of: 3 })}</p>
      <h1 className="text-2xl font-semibold">{title}</h1>
      {body && <p className="mt-1 text-road">{body}</p>}
    </div>
  )
}

function ReviewRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[7rem_1fr] gap-2 border-b border-hairline py-2 last:border-b-0">
      <dt className="text-road">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  )
}

/** Step 1: live camera plus the GPS fix. Mounted only on this step, so a retake starts a fresh fix. */
function PhotoStep({ busy, error, onShot }: { busy: boolean; error: unknown; onShot: (photo: Blob, fix: Fix) => void }) {
  const { t } = useTranslation()
  const gps = useGpsFix()
  const tone = gps.status === 'ok' ? 'border-asphalt' : gps.status === 'waiting' ? 'border-hairline' : 'border-overdue'
  return (
    <>
      <StepHeader n={1} title={t('report.photoTitle')} body={t('report.photoBody')} />
      <CameraCapture ready={gps.status === 'ok'} busy={busy} onShot={(photo) => { if (gps.fix) onShot(photo, gps.fix) }} />
      <p role="status" className={`mt-3 border-l-4 ${tone} pl-3 text-sm`}>
        {t(`report.gps.${gps.status}`, { accuracy: gps.fix ? Math.round(gps.fix.accuracy) : 0, max: MAX_GPS_ACCURACY_M })}
      </p>
      {error != null && <div className="mt-3"><ErrorBox error={error} /></div>}
      <p className="mt-6 border-l-4 border-hairline pl-3 text-sm text-road">{t('report.cameraOnlyHint')}</p>
      <p className="mt-3 border-l-4 border-hairline pl-3 text-sm text-road">{t('report.privacyHint')}</p>
    </>
  )
}

export default function Report() {
  const { t } = useTranslation()
  const api = useApi()
  const auth = useAuthState()
  const [step, setStep] = useState<Step>('photo')
  const [shot, setShot] = useState<Shot | null>(null)
  const [position, setPosition] = useState<[number, number] | null>(null)
  const [pinClamped, setPinClamped] = useState(false)
  const [preparing, setPreparing] = useState(false)
  const [captureError, setCaptureError] = useState<unknown>(null)
  const [analysis, setAnalysis] = useState<PhotoAnalysis | null>(null)
  const [analysisId, setAnalysisId] = useState<string | null>(null)
  const [aiDown, setAiDown] = useState(false)
  const [hazard, setHazard] = useState<HazardType | null>(null)
  const [severity, setSeverity] = useState(3)
  const [description, setDescription] = useState('')
  // Name and address start from the account and the map; once the person types, theirs wins.
  const [name, setName] = useState<string | null>(null)
  const [address, setAddress] = useState<string | null>(null)
  const [landmark, setLandmark] = useState('')
  const [result, setResult] = useState<ReportResult | null>(null)
  const [locationError, setLocationError] = useState<string | null>(null)
  const [retakeError, setRetakeError] = useState<string | null>(null)

  useEffect(() => () => { if (shot) URL.revokeObjectURL(shot.url) }, [shot])

  const settled = useDebounced(position, 700)
  const where = useQuery({
    queryKey: ['report-where', settled?.[0].toFixed(4), settled?.[1].toFixed(4)],
    queryFn: () => api<{ address: string | null }>('/reports/where', { params: { lat: settled![0], lng: settled![1] } }),
    enabled: Boolean(settled) && (step === 'location' || step === 'details'),
    staleTime: Infinity,
    retry: false,
  })
  const reporterName = name ?? auth.name ?? ''
  const reportAddress = address ?? where.data?.address ?? ''
  const nameOk = reporterName.trim().length >= 2

  async function takeShot(photo: Blob, fix: Fix) {
    setPreparing(true)
    setCaptureError(null)
    try {
      // The token ties this photo to the in-app camera; the photo check must follow within 10 minutes.
      const { capture_token } = await api<{ capture_token: string; expires_at: string }>('/reports/capture-start', { method: 'POST' })
      const ext = photo.type === 'image/webp' ? 'webp' : 'jpg'
      setShot({ file: new File([photo], `report.${ext}`, { type: photo.type }), url: URL.createObjectURL(photo), token: capture_token, fix, takenAt: new Date().toISOString() })
      setPosition([fix.lat, fix.lng])
      setPinClamped(false)
      setStep('location')
    } catch (err) {
      setCaptureError(err)
    } finally {
      setPreparing(false)
    }
  }

  const analyze = useMutation({
    mutationFn: () => {
      const form = new FormData()
      form.append('photo', shot!.file)
      form.append('lat', String(position![0]))
      form.append('lng', String(position![1]))
      form.append('capture_token', shot!.token)
      form.append('gps_lat', String(shot!.fix.lat))
      form.append('gps_lng', String(shot!.fix.lng))
      form.append('gps_accuracy_m', String(shot!.fix.accuracy))
      return api<PhotoAnalysis>('/reports/analyze', { form })
    },
    onSuccess: (a) => {
      setAnalysis(a)
      setAnalysisId(a.analysis_id)
      setAiDown(false)
      setHazard(a.is_road_hazard ? a.suggested_type : null)
      setSeverity(a.suggested_severity || 3)
      setStep('details')
    },
    onError: (err) => {
      if (err instanceof ApiError && err.code === 'AI_UNAVAILABLE') {
        // The photo was kept; the person picks the type themselves (T4.5).
        setAiDown(true)
        setAnalysis(null)
        setAnalysisId((err.details.analysis_id as string) ?? null)
        setStep('details')
      } else if (err instanceof ApiError && LOCATION_ERRORS.includes(err.code)) {
        setLocationError(t(`report.errors.${err.code}`, errorVars(err)))
      } else if (err instanceof ApiError && RETAKE_ERRORS.includes(err.code)) {
        setRetakeError(t(`report.errors.${err.code}`, errorVars(err)))
      }
    },
  })

  const submit = useMutation({
    mutationFn: () =>
      api<ReportResult>('/reports', {
        method: 'POST',
        body: {
          analysis_id: analysisId,
          hazard_type: hazard,
          severity,
          lat: position![0],
          lng: position![1],
          description: description.trim() || null,
          reporter_name: reporterName.trim(),
          address: reportAddress.trim() || null,
          landmark: landmark.trim() || null,
        },
      }),
    onSuccess: (r) => {
      setResult(r)
      setStep('done')
      // Next time the name is already filled in, on any device (U3b).
      void auth.saveReporterName(reporterName.trim()).catch(() => {})
    },
  })

  function reset() {
    setStep('photo'); setShot(null); setPosition(null); setPinClamped(false); setCaptureError(null); setAnalysis(null)
    setAnalysisId(null); setAiDown(false); setHazard(null); setSeverity(3); setDescription(''); setAddress(null); setLandmark('')
    setResult(null); setLocationError(null); setRetakeError(null); analyze.reset(); submit.reset()
  }

  function movePin(to: [number, number]) {
    if (!shot) return
    const next = clampToCircle(shot.fix, to)
    setPinClamped(next[0] !== to[0] || next[1] !== to[1])
    setPosition(next)
    setLocationError(null)
  }

  const moved = shot && position ? Math.round(metresBetween([shot.fix.lat, shot.fix.lng], position)) : 0

  return (
    <div className="mx-auto max-w-lg px-4 py-6 sm:py-10">
      {step === 'photo' && <PhotoStep busy={preparing} error={captureError} onShot={(photo, fix) => void takeShot(photo, fix)} />}

      {step === 'location' && shot && position && (
        <>
          <StepHeader n={2} title={t('report.locationTitle')} body={t('report.locationFromGps', { accuracy: Math.round(shot.fix.accuracy) })} />
          <div className="relative h-72 overflow-hidden rounded border border-hairline sm:h-80">
            <MapContainer center={position} zoom={18} className="h-full w-full">
              <TileLayer url={TILE_URL} attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' />
              <Recentre at={position} />
              <Circle center={[shot.fix.lat, shot.fix.lng]} radius={MAX_PIN_SHIFT_M}
                pathOptions={{ color: '#2E3236', weight: 1.5, dashArray: '4 4', fillOpacity: 0.05 }} />
              <Marker position={position} draggable icon={pin} title={t('report.dragPin')}
                eventHandlers={{ dragend: (e) => { const ll = e.target.getLatLng(); movePin([ll.lat, ll.lng]) } }} />
            </MapContainer>
          </div>
          <p className="mt-2 text-sm text-road">{t('report.dragPinWithin', { max: MAX_PIN_SHIFT_M })}</p>
          {pinClamped && <p role="status" className="mt-2 border-l-4 border-hairline pl-3 text-sm">{t('report.pinClamped', { max: MAX_PIN_SHIFT_M })}</p>}
          <p className="mt-3 text-sm">
            <span className="text-road">{t('report.address')}: </span>
            {where.isFetching ? t('report.addressLooking') : where.data?.address ?? t('report.addressUnknown')}
          </p>
          {locationError && <p role="alert" className="mt-3 border-l-4 border-overdue pl-3 text-sm">{locationError}</p>}
          {retakeError && (
            <div role="alert" className="mt-3 border-l-4 border-overdue bg-kerb p-3 text-sm">
              <p>{retakeError}</p>
              <Button className="mt-3" onClick={reset}>{t('report.retake')}</Button>
            </div>
          )}
          {analyze.isError && !locationError && !retakeError && <div className="mt-3"><ErrorBox error={analyze.error} /></div>}
          <div className="mt-5 flex flex-col gap-3">
            {analysisId ? (
              // The photo was checked already, and its token is spent: go on without checking again.
              <Button variant="primary" className="w-full" onClick={() => setStep('details')}>{t('report.continue')}</Button>
            ) : (
              <Button variant="primary" className="w-full" disabled={analyze.isPending || Boolean(retakeError)}
                onClick={() => { setLocationError(null); analyze.mutate() }}>
                {analyze.isPending ? t('report.checking') : t('report.checkPhoto')}
              </Button>
            )}
            <div className="flex gap-3">
              <Button className="flex-1" onClick={() => movePin([shot.fix.lat, shot.fix.lng])}>{t('report.pinToPhoto')}</Button>
              <Button variant="quiet" className="flex-1" onClick={reset}>{t('report.startOver')}</Button>
            </div>
          </div>
        </>
      )}

      {step === 'details' && shot && position && (
        <>
          <StepHeader n={3} title={t('report.detailsTitle')} />
          <img src={shot.url} alt={t('report.yourPhoto')} className="mb-4 max-h-56 w-full rounded object-cover" />
          {analysis?.is_road_hazard && analysis.suggested_type && (
            <div className="mb-5 border-l-4 border-marking bg-kerb p-3">
              <p className="text-sm font-semibold">{t('report.aiSuggested')}</p>
              <p className="mt-1">{t('report.aiSays', { hazard: t(HAZARDS[analysis.suggested_type].labelKey), severity: analysis.suggested_severity, confidence: Math.round(analysis.confidence * 100) })}</p>
              {analysis.reasons.length > 0 && <ul className="mt-1 list-disc pl-5 text-sm text-road">{analysis.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
              {analysis.uncertain && <p className="mt-1 text-sm text-road">{t('report.aiUncertain')}</p>}
            </div>
          )}
          {analysis && !analysis.is_road_hazard && <p role="status" className="mb-5 border-l-4 border-hairline pl-3">{t('report.notHazard')}</p>}
          {aiDown && <p role="status" className="mb-5 border-l-4 border-hairline pl-3">{t('report.aiDown')}</p>}

          <fieldset>
            <legend className="mb-2 font-semibold">{t('report.whatIsIt')}</legend>
            <div className="grid gap-2">
              {HAZARD_TYPES.map((h) => (
                <label key={h} className={`flex min-h-14 cursor-pointer items-center gap-3 rounded border px-3 ${hazard === h ? 'border-asphalt bg-kerb ring-2 ring-asphalt' : 'border-hairline bg-kerb'}`}>
                  <input type="radio" name="hazard" value={h} checked={hazard === h} onChange={() => setHazard(h)} className="sr-only" />
                  <HazardIcon type={h} size={28} />
                  <span className="text-lg">{t(HAZARDS[h].labelKey)}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset className="mt-5">
            <legend className="mb-2 font-semibold">{t('report.howBad')}</legend>
            <div className="grid grid-cols-5 gap-1">
              {[1, 2, 3, 4, 5].map((s) => (
                <label key={s} className={`flex min-h-12 cursor-pointer items-center justify-center rounded border text-lg font-semibold ${severity === s ? 'border-asphalt bg-asphalt text-kerb' : 'border-hairline bg-kerb'}`}>
                  <input type="radio" name="severity" value={s} checked={severity === s} onChange={() => setSeverity(s)} className="sr-only" />
                  {s}
                </label>
              ))}
            </div>
            <p className="mt-2 text-sm text-road">{t(`report.severity.${severity}`)}</p>
          </fieldset>

          <label className="mt-5 block">
            <span className="font-semibold">{t('report.notes')}</span>
            <span className="block text-sm text-road">{t('report.notesHint')}</span>
            <textarea value={description} maxLength={500} onChange={(e) => setDescription(e.target.value)} rows={3}
              className="mt-1 w-full rounded border border-road bg-kerb p-3" />
          </label>

          <fieldset className="mt-6 space-y-4">
            <legend className="mb-1 font-semibold">{t('report.yourDetails')}</legend>
            <Field label={t('report.name')} hint={t('report.nameHint')} value={reporterName} maxLength={80} autoComplete="name" required
              error={name !== null && !nameOk ? t('report.nameMissing') : undefined} onChange={(e) => setName(e.target.value)} />
            <Field label={t('report.address')} hint={where.isFetching && address === null ? t('report.addressLooking') : t('report.addressHint')}
              value={reportAddress} maxLength={200} autoComplete="off" onChange={(e) => setAddress(e.target.value)} />
            <Field label={t('report.landmark')} hint={t('report.landmarkHint')} value={landmark} maxLength={120} autoComplete="off"
              onChange={(e) => setLandmark(e.target.value)} />
          </fieldset>

          <section aria-labelledby="report-review" className="mt-6 rounded border border-hairline bg-kerb p-3">
            <h2 id="report-review" className="font-semibold">{t('report.reviewTitle')}</h2>
            <dl className="mt-2 text-sm">
              <ReviewRow label={t('report.name')}>{reporterName.trim() || '—'}</ReviewRow>
              <ReviewRow label={t('report.address')}>{reportAddress.trim() || '—'}</ReviewRow>
              {landmark.trim() && <ReviewRow label={t('report.landmark')}>{landmark.trim()}</ReviewRow>}
              <ReviewRow label={t('report.gpsLabel')}>
                <span className="tabular">{shot.fix.lat.toFixed(5)}, {shot.fix.lng.toFixed(5)}</span>{' '}
                {t('report.gpsAccuracy', { accuracy: Math.round(shot.fix.accuracy) })}
                {moved > 5 && <span className="block text-road">{t('report.pinMoved', { metres: moved })}</span>}
              </ReviewRow>
              <ReviewRow label={t('report.takenAt')}>{formatDateTime(shot.takenAt)}</ReviewRow>
            </dl>
          </section>

          {submit.isError && <div className="mt-4"><ErrorBox error={submit.error} /></div>}
          <Button variant="primary" className="mt-5 w-full" disabled={!hazard || !nameOk || !analysisId || submit.isPending} onClick={() => submit.mutate()}>
            {submit.isPending ? t('report.sending') : t('report.send')}
          </Button>
          <Button variant="quiet" className="mt-2 w-full" onClick={() => setStep('location')}>{t('report.back')}</Button>
        </>
      )}

      {step === 'done' && result && (
        <div aria-live="polite">
          <p className="text-sm text-road">{result.merged_into ? t('report.mergedTitle') : t('report.sentTitle')}</p>
          <h1 className="mt-1 font-condensed text-4xl font-semibold tabular">{result.ref_no}</h1>
          <p className="mt-2">{result.merged_into ? t('report.mergedBody', { count: result.confirmations ?? 2 }) : t('report.sentBody')}</p>
          <dl className="mt-6 border-y border-hairline">
            <div className="flex items-center gap-2 border-b border-hairline py-3">
              <RoutePlate roadClass={result.segment.road_class} routeRef={result.segment.ref} />
              <span className="font-condensed text-lg font-semibold">{result.segment.name ?? t('common.unnamedRoad')}</span>
            </div>
            <div className="grid grid-cols-[8rem_1fr] gap-2 border-b border-hairline py-3 text-sm">
              <dt className="text-road">{t('drawer.owner')}</dt><dd>{result.responsible.owner}</dd>
            </div>
            <div className="grid grid-cols-[8rem_1fr] gap-2 border-b border-hairline py-3 text-sm">
              <dt className="text-road">{t('drawer.maintainer')}</dt><dd>{result.responsible.maintainer}</dd>
            </div>
            {result.sla_due_at && (
              <div className="grid grid-cols-[8rem_1fr] gap-2 py-3 text-sm">
                <dt className="text-road">{t('drawer.sla')}</dt><dd>{t('report.slaBy', { when: formatRelative(result.sla_due_at) })}</dd>
              </div>
            )}
          </dl>
          <div className="mt-6 flex flex-col gap-3">
            <Link to={`/report/${result.ref_no}`} className={buttonClass('primary', 'w-full')}>{t('report.track')}</Link>
            <Button className="w-full" onClick={reset}>{t('report.another')}</Button>
          </div>
        </div>
      )}
    </div>
  )
}

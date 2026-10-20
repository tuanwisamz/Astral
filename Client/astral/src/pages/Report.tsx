import 'leaflet/dist/leaflet.css'

import { useMutation } from '@tanstack/react-query'
import imageCompression from 'browser-image-compression'
import exifr from 'exifr'
import L from 'leaflet'
import { useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { MapContainer, Marker, TileLayer, useMap } from 'react-leaflet'

import { useApi } from '../app/auth'
import { Button, buttonClass } from '../components/ui/Button'
import { HazardIcon } from '../components/ui/HazardIcon'
import { RoutePlate } from '../components/ui/RoutePlate'
import { ErrorBox } from '../components/ui/Status'
import { ApiError } from '../lib/api'
import { formatRelative } from '../lib/format'
import { HAZARD_TYPES, HAZARDS, type HazardType } from '../lib/hazards'
import type { PhotoAnalysis, ReportResult } from '../lib/types'

const TILE_URL: string = import.meta.env.VITE_MAP_TILE_URL ?? 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const UTP: [number, number] = [4.3826, 100.9704] // focus area: UTP Seri Iskandar (plan A2)
type Step = 'photo' | 'location' | 'details' | 'done'

interface Photo {
  file: File
  url: string
}

const pin = L.divIcon({
  className: 'hazard-marker',
  html: '<svg width="34" height="44" viewBox="0 0 34 44" aria-hidden="true"><path d="M17 43s15-15.6 15-26A15 15 0 0 0 2 17c0 10.4 15 26 15 26z" fill="#2E3236" stroke="#fff" stroke-width="2"/><circle cx="17" cy="17" r="6" fill="#F5C400"/></svg>',
  iconSize: [34, 44],
  iconAnchor: [17, 43],
})

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

export default function Report() {
  const { t } = useTranslation()
  const api = useApi()
  const [step, setStep] = useState<Step>('photo')
  const [photo, setPhoto] = useState<Photo | null>(null)
  const [position, setPosition] = useState<[number, number] | null>(null)
  const [gpsSource, setGpsSource] = useState<'photo' | 'device' | 'none'>('none')
  const [preparing, setPreparing] = useState(false)
  const [analysis, setAnalysis] = useState<PhotoAnalysis | null>(null)
  const [analysisId, setAnalysisId] = useState<string | null>(null)
  const [aiDown, setAiDown] = useState(false)
  const [hazard, setHazard] = useState<HazardType | null>(null)
  const [severity, setSeverity] = useState(3)
  const [description, setDescription] = useState('')
  const [result, setResult] = useState<ReportResult | null>(null)
  const [locationError, setLocationError] = useState<string | null>(null)
  const cameraInput = useRef<HTMLInputElement>(null)
  const galleryInput = useRef<HTMLInputElement>(null)

  useEffect(() => () => { if (photo) URL.revokeObjectURL(photo.url) }, [photo])

  function locateDevice() {
    if (!navigator.geolocation) return
    navigator.geolocation.getCurrentPosition(
      (p) => { setPosition([p.coords.latitude, p.coords.longitude]); setGpsSource('device') },
      () => setGpsSource((s) => (s === 'photo' ? s : 'none')),
      { enableHighAccuracy: true, timeout: 10_000 },
    )
  }

  async function onPhoto(e: ChangeEvent<HTMLInputElement>) {
    const original = e.target.files?.[0]
    e.target.value = ''
    if (!original) return
    setPreparing(true)
    try {
      // GPS first: compression re-encodes the image and drops EXIF (plan M4).
      const gps = await exifr.gps(original).catch(() => null)
      if (gps?.latitude && gps?.longitude) {
        setPosition([gps.latitude, gps.longitude])
        setGpsSource('photo')
      } else {
        locateDevice()
      }
      const small = await imageCompression(original, { maxWidthOrHeight: 1280, maxSizeMB: 0.4, fileType: 'image/webp', useWebWorker: true })
      setPhoto({ file: new File([small], 'report.webp', { type: 'image/webp' }), url: URL.createObjectURL(small) })
      setStep('location')
    } finally {
      setPreparing(false)
    }
  }

  const analyze = useMutation({
    mutationFn: () => {
      const form = new FormData()
      form.append('photo', photo!.file)
      form.append('lat', String(position![0]))
      form.append('lng', String(position![1]))
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
      } else if (err instanceof ApiError && ['NOT_ON_ROAD', 'OUTSIDE_COVERAGE'].includes(err.code)) {
        setLocationError(t(`report.errors.${err.code}`))
      }
    },
  })

  const submit = useMutation({
    mutationFn: () =>
      api<ReportResult>('/reports', {
        method: 'POST',
        body: { analysis_id: analysisId, hazard_type: hazard, severity, lat: position![0], lng: position![1], description: description || null },
      }),
    onSuccess: (r) => { setResult(r); setStep('done') },
  })

  function reset() {
    setStep('photo'); setPhoto(null); setPosition(null); setAnalysis(null); setAnalysisId(null); setAiDown(false)
    setHazard(null); setSeverity(3); setDescription(''); setResult(null); setLocationError(null); analyze.reset(); submit.reset()
  }

  const centre = useMemo<[number, number]>(() => position ?? UTP, [position])

  return (
    <div className="mx-auto max-w-lg px-4 py-6 sm:py-10">
      {step === 'photo' && (
        <>
          <StepHeader n={1} title={t('report.photoTitle')} body={t('report.photoBody')} />
          <input ref={cameraInput} type="file" accept="image/*" capture="environment" className="sr-only" onChange={onPhoto} />
          <input ref={galleryInput} type="file" accept="image/*" className="sr-only" onChange={onPhoto} />
          <button type="button" onClick={() => cameraInput.current?.click()} disabled={preparing}
            className="flex min-h-40 w-full flex-col items-center justify-center gap-3 rounded border-2 border-asphalt bg-marking text-xl font-semibold text-asphalt disabled:opacity-60">
            <svg width="44" height="44" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8h3l2-3h6l2 3h3v11H4z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /><circle cx="12" cy="13" r="3.5" fill="none" stroke="currentColor" strokeWidth="1.8" /></svg>
            {preparing ? t('report.preparing') : t('report.takePhoto')}
          </button>
          <Button variant="quiet" className="mt-3 w-full" onClick={() => galleryInput.current?.click()} disabled={preparing}>
            {t('report.choosePhoto')}
          </Button>
          <p className="mt-6 border-l-4 border-hairline pl-3 text-sm text-road">{t('report.privacyHint')}</p>
        </>
      )}

      {step === 'location' && photo && (
        <>
          <StepHeader n={2} title={t('report.locationTitle')}
            body={gpsSource === 'photo' ? t('report.locationFromPhoto') : gpsSource === 'device' ? t('report.locationFromDevice') : t('report.locationNone')} />
          <div className="relative h-72 overflow-hidden rounded border border-hairline sm:h-80">
            <MapContainer center={centre} zoom={position ? 17 : 13} className="h-full w-full">
              <TileLayer url={TILE_URL} attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' />
              <Recentre at={centre} />
              <Marker position={centre} draggable icon={pin} title={t('report.dragPin')}
                eventHandlers={{ dragend: (e) => { const ll = e.target.getLatLng(); setPosition([ll.lat, ll.lng]); setLocationError(null) } }} />
            </MapContainer>
          </div>
          <p className="mt-2 text-sm text-road">{t('report.dragPin')}</p>
          {locationError && <p role="alert" className="mt-3 border-l-4 border-overdue pl-3 text-sm">{locationError}</p>}
          {analyze.isError && !locationError && <div className="mt-3"><ErrorBox error={analyze.error} /></div>}
          <div className="mt-5 flex flex-col gap-3">
            <Button variant="primary" className="w-full" disabled={!position || analyze.isPending} onClick={() => { setLocationError(null); analyze.mutate() }}>
              {analyze.isPending ? t('report.checking') : t('report.checkPhoto')}
            </Button>
            <div className="flex gap-3">
              <Button className="flex-1" onClick={locateDevice}>{t('report.useMyLocation')}</Button>
              <Button variant="quiet" className="flex-1" onClick={reset}>{t('report.startOver')}</Button>
            </div>
          </div>
        </>
      )}

      {step === 'details' && (
        <>
          <StepHeader n={3} title={t('report.detailsTitle')} />
          {photo && <img src={photo.url} alt={t('report.yourPhoto')} className="mb-4 max-h-56 w-full rounded object-cover" />}
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

          {submit.isError && <div className="mt-4"><ErrorBox error={submit.error} /></div>}
          <Button variant="primary" className="mt-5 w-full" disabled={!hazard || submit.isPending} onClick={() => submit.mutate()}>
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

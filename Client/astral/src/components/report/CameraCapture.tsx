import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Button } from '../ui/Button'

type CameraState = 'starting' | 'live' | 'denied' | 'unavailable'
type Problem = 'insecure' | 'denied' | 'unavailable'

const MAX_SIDE = 1280 // the server resizes to this anyway (services/photos.py)

/** The current video frame, scaled to MAX_SIDE, as WebP (JPEG where the browser can't make WebP). */
async function grabFrame(video: HTMLVideoElement): Promise<Blob> {
  const scale = Math.min(1, MAX_SIDE / Math.max(video.videoWidth, video.videoHeight))
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(video.videoWidth * scale)
  canvas.height = Math.round(video.videoHeight * scale)
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Could not capture the photo')
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
  const encode = (type: string) => new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, type, 0.85))
  const webp = await encode('image/webp')
  // Safari can't encode WebP and quietly returns PNG, which can pass the 3 MB limit; JPEG stays small.
  const blob = webp?.type === 'image/webp' ? webp : await encode('image/jpeg')
  if (!blob) throw new Error('Could not capture the photo')
  return blob
}

/**
 * Live camera for hazard reports (U3a). Photos come only from this preview, never from the
 * gallery or a file picker, so a report can't reuse an old or downloaded picture.
 */
export function CameraCapture({ ready, busy, onShot }: {
  /** False until the phone has a good enough GPS fix; the shutter waits for it. */
  ready: boolean
  busy: boolean
  onShot: (photo: Blob) => void
}) {
  const { t } = useTranslation()
  const video = useRef<HTMLVideoElement>(null)
  const [state, setState] = useState<CameraState>('starting')
  const [attempt, setAttempt] = useState(0)
  const [shooting, setShooting] = useState(false)
  // The camera only opens on HTTPS (or localhost), and some browsers have no camera API at all.
  const insecure = !window.isSecureContext
  const supported = Boolean(navigator.mediaDevices?.getUserMedia)

  useEffect(() => {
    if (insecure || !supported) return
    let stream: MediaStream | null = null
    let cancelled = false
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false })
      .then(async (s) => {
        if (cancelled) {
          s.getTracks().forEach((track) => track.stop())
          return
        }
        stream = s
        if (video.current) {
          video.current.srcObject = s
          await video.current.play().catch(() => {})
        }
        setState('live')
      })
      .catch((err: unknown) => {
        if (cancelled) return
        const name = err instanceof DOMException ? err.name : ''
        setState(name === 'NotAllowedError' || name === 'SecurityError' ? 'denied' : 'unavailable')
      })
    return () => {
      cancelled = true
      stream?.getTracks().forEach((track) => track.stop())
    }
  }, [attempt, insecure, supported])

  const problem: Problem | null = insecure ? 'insecure' : !supported ? 'unavailable'
    : state === 'denied' || state === 'unavailable' ? state : null

  async function shoot() {
    if (!video.current || shooting) return
    setShooting(true)
    try {
      onShot(await grabFrame(video.current))
    } finally {
      setShooting(false)
    }
  }

  return (
    <div>
      <div className="relative aspect-[3/4] w-full overflow-hidden rounded border-2 border-asphalt bg-asphalt sm:aspect-video">
        <video ref={video} playsInline muted autoPlay aria-label={t('report.camera.preview')}
          className={`h-full w-full object-cover ${problem ? 'hidden' : ''}`} />
        {state === 'starting' && !problem && (
          <p className="absolute inset-0 grid place-items-center text-kerb">{t('report.camera.starting')}</p>
        )}
        {problem && (
          <div role="alert" className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center text-kerb">
            <p className="text-lg font-semibold">{t(`report.camera.${problem}Title`)}</p>
            <p className="max-w-prose text-sm text-kerb/80">{t(`report.camera.${problem}Body`)}</p>
            {problem === 'denied' && (
              <Button onClick={() => { setState('starting'); setAttempt((n) => n + 1) }}>{t('app.retry')}</Button>
            )}
          </div>
        )}
      </div>
      <button type="button" onClick={() => void shoot()} disabled={state !== 'live' || Boolean(problem) || !ready || busy || shooting}
        className="mt-3 flex min-h-16 w-full items-center justify-center gap-3 rounded border-2 border-asphalt bg-marking text-xl font-semibold text-asphalt disabled:cursor-not-allowed disabled:opacity-60">
        <svg width="32" height="32" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8h3l2-3h6l2 3h3v11H4z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /><circle cx="12" cy="13" r="3.5" fill="none" stroke="currentColor" strokeWidth="1.8" /></svg>
        {busy || shooting ? t('report.preparing') : t('report.takePhoto')}
      </button>
    </div>
  )
}

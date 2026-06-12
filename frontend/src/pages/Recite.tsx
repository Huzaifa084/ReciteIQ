import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { Recorder } from '../audio/recorder'
import { JumpBanner } from '../components/JumpBanner'
import { MushafView } from '../components/MushafView'
import { applyEvents, initialState, type ReciteState } from '../state/reducer'
import type { DisplayAyah, SurahInfo } from '../types'
import { SessionSocket } from '../ws/client'

export function Recite({
  surahs,
  surahId,
  startAyah,
  onFinished,
  onJumpAccepted,
}: {
  surahs: SurahInfo[]
  surahId: number
  startAyah: number
  onFinished: (sessionId: string) => void
  onJumpAccepted: (destSurah: number, destAyah: number) => void
}) {
  const [ayahs, setAyahs] = useState<DisplayAyah[]>([])
  const [state, setState] = useState<ReciteState>(initialState())
  const [status, setStatus] = useState<'starting' | 'live' | 'muted' | 'error'>('starting')
  const [error, setError] = useState('')
  const sockRef = useRef<SessionSocket | null>(null)
  const recRef = useRef<Recorder | null>(null)
  const sessionRef = useRef<string>('')
  const mutedRef = useRef(false)

  const teardown = useCallback(() => {
    recRef.current?.stop()
    sockRef.current?.close()
    recRef.current = null
    sockRef.current = null
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [text, session] = await Promise.all([
          api.surahText(surahId, startAyah),
          api.createSession(surahId, startAyah),
        ])
        if (cancelled) return
        setAyahs(text)
        sessionRef.current = session.session_id

        const sock = new SessionSocket(session.session_id, {
          onEvents: (events) => setState((prev) => applyEvents(prev, events)),
          onEnded: () => {
            teardown()
            onFinished(sessionRef.current)
          },
          onRejected: (reason) => {
            setError(reason === 'busy' ? 'All listening slots are busy — try again shortly.' : reason)
            setStatus('error')
            teardown()
          },
          onStatusChange: () => {},
        })
        sockRef.current = sock
        sock.connect()

        const rec = new Recorder()
        recRef.current = rec
        await rec.start((pcm) => {
          if (!mutedRef.current) sockRef.current?.sendAudio(pcm)
        })
        if (!cancelled) setStatus('live')
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e))
          setStatus('error')
        }
      }
    })()
    return () => {
      cancelled = true
      teardown()
    }
  }, [surahId, startAyah, teardown, onFinished])

  const toggleMute = () => {
    mutedRef.current = !mutedRef.current
    setStatus(mutedRef.current ? 'muted' : 'live')
  }

  const endSession = () => {
    sockRef.current?.end() // server replies 'ended' -> onEnded -> summary
  }

  const surah = surahs.find((s) => s.id === surahId)

  return (
    <div className="page recite">
      <header className="recite-header">
        <h2>
          {surah?.name_english} <span dir="rtl">{surah?.name_arabic}</span>
        </h2>
        <div className="controls">
          <span className={`status status-${status}`}>
            {status === 'live' ? '● listening' : status === 'muted' ? '⏸ paused' : status}
          </span>
          <button onClick={toggleMute} disabled={status === 'starting' || status === 'error'}>
            {status === 'muted' ? 'Resume' : 'Pause'}
          </button>
          <button className="danger" onClick={endSession} disabled={status === 'starting'}>
            End Session
          </button>
        </div>
      </header>

      {error && <div className="error">{error}</div>}

      {state.jump && (
        <JumpBanner
          jump={state.jump}
          surahs={surahs}
          onContinueHere={() => {
            const j = state.jump!
            teardown()
            api.endSession(sessionRef.current).finally(() => onJumpAccepted(j.destSurah, j.destAyah))
          }}
          onDismiss={() => setState((s) => ({ ...s, jump: null }))}
        />
      )}

      <MushafView ayahs={ayahs} state={state} />

      <footer className="legend">
        <span className="word-ok">recited</span>
        <span className="word-missed">missed</span>
        <span className="word-missed-provisional">checking…</span>
        <span className="word-current">current</span>
      </footer>
    </div>
  )
}

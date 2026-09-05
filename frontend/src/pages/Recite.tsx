import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { Recorder } from '../audio/recorder'
import { JumpBanner } from '../components/JumpBanner'
import { MushafView, WORD_STATUS_LABEL } from '../components/MushafView'
import type { WordDetail } from '../components/MushafView'
import { applyEvents, initialState, type ReciteState } from '../state/reducer'
import { TopBar } from '../components/TopBar'
import type { DisplayAyah, SurahInfo } from '../types'
import { SessionSocket } from '../ws/client'

const WaveIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M3 13.5a1 1 0 0 1-1-1v-1a1 1 0 1 1 2 0v1a1 1 0 0 1-1 1zm4.5 3a1 1 0 0 1-1-1v-7a1 1 0 1 1 2 0v7a1 1 0 0 1-1 1zm4.5 3a1 1 0 0 1-1-1v-13a1 1 0 1 1 2 0v13a1 1 0 0 1-1 1zm4.5-3a1 1 0 0 1-1-1v-7a1 1 0 1 1 2 0v7a1 1 0 0 1-1 1zm4.5-3a1 1 0 0 1-1-1v-1a1 1 0 1 1 2 0v1a1 1 0 0 1-1 1z" />
  </svg>
)

export function Recite({
  surahs,
  surahId,
  startAyah,
  auto = false,
  onHome,
  onFinished,
  onJumpAccepted,
}: {
  surahs: SurahInfo[]
  surahId: number | null
  startAyah: number
  auto?: boolean
  onHome: () => void
  onFinished: (sessionId: string) => void
  onJumpAccepted: (destSurah: number, destAyah: number) => void
}) {
  const [ayahs, setAyahs] = useState<DisplayAyah[]>([])
  const [state, setState] = useState<ReciteState>(initialState())
  const [status, setStatus] = useState<'starting' | 'detecting' | 'live' | 'muted' | 'error'>(
    'starting',
  )
  // Connection health, tracked separately from tracking state: the socket can
  // be down while the tracker is mid-surah. Leaving this unwired meant the app
  // kept saying "listening" through five failed reconnects (B-7).
  const [link, setLink] = useState<'ok' | 'reconnecting' | 'lost'>('ok')
  const [detectedSurah, setDetectedSurah] = useState<number | null>(auto ? null : surahId)
  const [noMatchRun, setNoMatchRun] = useState(0)   // P0-4: consecutive unplaced windows
  // Seconds of speech held in the window the server has not closed yet. With a
  // 25s window this is the only sign of life for up to ~28s, and for a short
  // surah for the whole recitation — without it the app reads as broken.
  const [heard, setHeard] = useState(0)
  // A flagged word the reciter tapped. Colour alone does not say WHAT happened,
  // and after a long session the summary list is a poor way to find one word.
  const [inspected, setInspected] = useState<(WordDetail & { idx: number }) | null>(null)
  // Transient acknowledgement of a restart. Held separately from state.repeat so
  // it can fade on its own without touching tracking state.
  const [restart, setRestart] = useState<{ ayah: number; seq: number } | null>(null)
  const [error, setError] = useState('')
  const sockRef = useRef<SessionSocket | null>(null)
  const recRef = useRef<Recorder | null>(null)
  const sessionRef = useRef<string>('')
  const mutedRef = useRef(false)
  const ringRef = useRef<HTMLDivElement | null>(null)

  const teardown = useCallback(() => {
    recRef.current?.stop()
    sockRef.current?.close()
    recRef.current = null
    sockRef.current = null
  }, [])

  // A restart is benign, so this appears and leaves on its own rather than
  // demanding a dismissal.
  useEffect(() => {
    if (!state.repeat) return
    setRestart({ ayah: state.repeat.ayah, seq: state.repeat.seq })
    const t = setTimeout(() => setRestart(null), 4500)
    return () => clearTimeout(t)
  }, [state.repeat?.seq])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [text, session] = await Promise.all([
          auto ? Promise.resolve([] as DisplayAyah[]) : api.surahText(surahId!, startAyah),
          api.createSession(surahId, startAyah, auto),
        ])
        if (cancelled) return
        setAyahs(text)
        sessionRef.current = session.session_id

        const sock = new SessionSocket(session.session_id, {
          onEvents: (events) => {
            setState((prev) => applyEvents(prev, events))
            setNoMatchRun(0)      // anything placed clears the warning
            setHeard(0)           // the window closed; the pending count is stale
          },
          onNoMatch: (info) => setNoMatchRun(info.run || 1),
          onBuffering: (info) => setHeard(info.bufferedSec),
          onDetected: (surah, ayah) => {
            setDetectedSurah(surah)
            api.surahText(surah, ayah).then((t) => {
              setAyahs(t)
              setStatus(mutedRef.current ? 'muted' : 'live')
            })
          },
          onEnded: () => {
            teardown()
            onFinished(sessionRef.current)
          },
          onRejected: (reason) => {
            setError(reason === 'busy' ? 'All listening slots are busy — try again shortly.' : reason)
            setStatus('error')
            teardown()
          },
          onStatusChange: (st) => {
            if (st === 'open') setLink('ok')
            else if (st === 'reconnecting') setLink('reconnecting')
            else if (st === 'lost') {
              setLink('lost')
              // Stop the microphone: nothing is reaching the server, and
              // letting them recite into it wastes their time.
              recRef.current?.stop()
              setError('Connection lost. Your progress so far is saved — finish to see it.')
            }
          },
        })
        sockRef.current = sock
        sock.connect()

        const rec = new Recorder()
        recRef.current = rec
        await rec.start(
          (pcm) => {
            if (!mutedRef.current) sockRef.current?.sendAudio(pcm)
          },
          (rms) => {
            // drive the voice ring without re-rendering React on every chunk
            const lvl = mutedRef.current ? 0 : Math.min(1, rms * 4)
            ringRef.current?.style.setProperty('--level', lvl.toFixed(2))
          },
        )
        if (!cancelled) setStatus(auto ? 'detecting' : 'live')
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
  }, [surahId, startAyah, auto, teardown, onFinished])

  const totalWords = useMemo(() => ayahs.reduce((n, a) => n + a.words.length, 0), [ayahs])
  const okWords = useMemo(() => {
    let n = 0
    for (const st of state.words.values()) if (st === 'ok') n++
    return n
  }, [state.words])

  const toggleMute = () => {
    mutedRef.current = !mutedRef.current
    setStatus(mutedRef.current ? 'muted' : 'live')
  }

  const surah = surahs.find((s) => s.id === detectedSurah)
  const pillClass =
    link !== 'ok' ? 'muted'
    : status === 'live' ? 'live' : status === 'muted' ? 'muted' : status === 'detecting' ? 'detecting' : ''
  const pillText =
    link === 'lost'
      ? 'connection lost'
      : link === 'reconnecting'
      ? 'reconnecting…'
      : status === 'live' && noMatchRun >= 2
      ? "can't place you"
      : status === 'live' && heard >= 3
      ? `hearing you · ${Math.round(heard)}s`
      : status === 'live'
      ? 'listening'
      : status === 'detecting'
        ? 'detecting location…'
        : status === 'muted'
          ? 'paused'
          : status

  return (
    <div className="page recite">
      <TopBar onHome={onHome} confirmLeave={status === 'live' || status === 'detecting'} />
      <header className="recite-header">
        <div className="recite-title">
          <div className="voice-ring" ref={ringRef}>
            <WaveIcon />
          </div>
          <h2>{surah ? surah.name_english : 'ReciteIQ'}</h2>
          {surah && <span className="ar">{surah.name_arabic}</span>}
        </div>
        <div className="controls">
          <span className={`status-pill ${pillClass}`}>
            <span className="dot" />
            {pillText}
          </span>
          <button onClick={toggleMute} disabled={status === 'starting' || status === 'error'}>
            {status === 'muted' ? 'Resume' : 'Pause'}
          </button>
          <button
            className="danger"
            onClick={() => sockRef.current?.end()}
            disabled={status === 'starting'}
          >
            End Session
          </button>
        </div>
      </header>

      {totalWords > 0 && (
        <div className="progress-track" title={`${okWords} of ${totalWords} words`}>
          <div className="progress-fill" style={{ width: `${(okWords / totalWords) * 100}%` }} />
        </div>
      )}

      {error && <div className="error">{error}</div>}

      {status === 'detecting' && (
        <div className="detecting-hint">
          <span style={{ fontSize: 26 }}>🎙</span>
          <span>
            Just start reciting — ReciteIQ finds the Surah and Ayah from your voice. A few words
            are usually enough; similar passages may need one more ayah.
          </span>
        </div>
      )}

      {state.jump && (
        <JumpBanner
          jump={state.jump}
          from={state.position ? { surah: state.position.surah, ayah: state.position.ayah } : null}
          surahs={surahs}
          onContinueHere={() => {
            const j = state.jump!
            teardown()
            api.endSession(sessionRef.current).finally(() => onJumpAccepted(j.destSurah, j.destAyah))
          }}
          onDismiss={() => setState((s) => ({ ...s, jump: null }))}
        />
      )}

      {ayahs.length > 0 && (
        <div className="mushaf-frame">
          <div className="ornament" />
          <MushafView
            ayahs={ayahs}
            state={state}
            selectedIdx={inspected?.idx ?? null}
            onWordSelect={(d) => setInspected((cur) => (cur?.idx === d.idx ? null : d))}
          />
        </div>
      )}

      {restart && (
        <div className="restart-note" role="status" key={restart.seq}>
          Picked you up again from ayah {restart.ayah} — carry on.
        </div>
      )}

      {inspected && (
        <div className="word-detail" role="status">
          <span className="ar word-detail-word">{inspected.text}</span>
          <span className="word-detail-where">
            Ayah {inspected.ayah} · word {inspected.position}
          </span>
          <span className={`word-detail-verdict verdict-${inspected.status}`}>
            {WORD_STATUS_LABEL[inspected.status]}
          </span>
          <button className="word-detail-close" onClick={() => setInspected(null)} aria-label="Close">
            ×
          </button>
        </div>
      )}

      {ayahs.length > 0 && (
        <footer className="legend">
          <span><i className="i-ok" /> recited</span>
          <span><i className="i-heard" /> heard, not confirmed</span>
          <span><i className="i-missed" /> missed</span>
          <span className="legend-hint">tap a flagged word to see what happened</span>
          <span><i className="i-checking" /> checking…</span>
          <span><i className="i-unplaced" /> unplaced (still listening)</span>
          <span><i className="i-current" /> current position</span>
        </footer>
      )}
      {status === 'live' && noMatchRun >= 2 && (
        <div className="detecting-hint">
          <span>
            Hearing you, but not able to line it up with the text yet — carry on
            reciting, or check the Surah is the one you meant. Nothing here is being
            marked as a mistake.
          </span>
        </div>
      )}
    </div>
  )
}

import { useEffect, useState } from 'react'
import { api } from '../api'
import type { SessionSummaryData, SurahInfo } from '../types'

export function Summary({
  sessionId,
  surahs,
  onHome,
}: {
  sessionId: string
  surahs: SurahInfo[]
  onHome: () => void
}) {
  const [data, setData] = useState<{ surah_id: number; summary: SessionSummaryData | null } | null>(
    null,
  )

  useEffect(() => {
    // finalize (idempotent), then read the summary row
    api
      .endSession(sessionId)
      .then(() => api.summary(sessionId))
      .then(setData)
      .catch(() => setData(null))
  }, [sessionId])

  const s = data?.summary
  const surah = surahs.find((x) => x.id === data?.surah_id)
  const clean = s && s.words_missed === 0 && s.ayahs_missed === 0 && s.jumps === 0

  return (
    <div className="page summary">
      <h2>Session Summary {surah ? `— ${surah.name_english}` : ''}</h2>
      {!s ? (
        <p>Loading…</p>
      ) : (
        <>
          <div className="stats">
            <div className="stat ok">
              <strong>{s.words_ok}</strong> words recited
            </div>
            <div className={`stat ${s.words_missed ? 'bad' : ''}`}>
              <strong>{s.words_missed}</strong> missed words
            </div>
            <div className={`stat ${s.ayahs_missed ? 'bad' : ''}`}>
              <strong>{s.ayahs_missed}</strong> missed ayahs
            </div>
            <div className={`stat ${s.jumps ? 'bad' : ''}`}>
              <strong>{s.jumps}</strong> Mutashabeh jumps
            </div>
            <div className="stat">
              <strong>{Math.round(s.duration_sec / 60)}m {Math.round(s.duration_sec % 60)}s</strong>{' '}
              duration
            </div>
          </div>
          {clean && <p className="clean">✨ Flawless recitation — ما شاء الله</p>}
          {!clean && s.errors.length > 0 && (
            <ul className="error-list">
              {s.errors.map((e, i) => (
                <li key={i}>
                  {e.type === 'MISSED_WORD' &&
                    `Missed word — Ayah ${e.payload.ayah}, word ${e.payload.position}`}
                  {e.type === 'MISSED_AYAH' && `Missed Ayah ${e.payload.ayah} entirely`}
                  {e.type === 'MUTASHABEH_JUMP' &&
                    `Jumped to Surah ${e.payload.dest_surah}, Ayah ${e.payload.dest_ayah} (similar passage)`}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      <button className="primary" onClick={onHome}>
        New Session
      </button>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { api } from '../api'
import type { SessionSummaryData, SurahInfo } from '../types'

function AccuracyRing({ pct }: { pct: number }) {
  const r = 64
  const c = 2 * Math.PI * r
  const color = pct >= 90 ? 'var(--green)' : pct >= 70 ? 'var(--amber)' : 'var(--red)'
  return (
    <div className="ring">
      <svg width="150" height="150" viewBox="0 0 150 150">
        <circle cx="75" cy="75" r={r} fill="none" stroke="rgba(31,58,41,.8)" strokeWidth="11" />
        <circle
          cx="75"
          cy="75"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="11"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - pct / 100)}
          style={{ transition: 'stroke-dashoffset 1s ease' }}
        />
      </svg>
      <div className="ring-label">
        <div>
          <span className="pct">{pct}%</span>
          <span className="pct-sub">accuracy</span>
        </div>
      </div>
    </div>
  )
}

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
  const attempted = s ? s.words_ok + s.words_missed : 0
  const pct = s && attempted > 0 ? Math.round((s.words_ok / attempted) * 100) : 0
  const mins = s ? Math.floor(s.duration_sec / 60) : 0
  const secs = s ? Math.round(s.duration_sec % 60) : 0

  return (
    <div className="page summary">
      {!s ? (
        <p style={{ color: 'var(--muted)' }}>Preparing your summary…</p>
      ) : (
        <>
          <section className="summary-hero panel">
            <AccuracyRing pct={pct} />
            <div className="summary-copy">
              <h2>
                {surah ? surah.name_english : 'Session'}{' '}
                {surah && <span className="ar">{surah.name_arabic}</span>}
              </h2>
              {clean ? (
                <div className="clean">
                  Flawless recitation — <span className="ar">مَا شَاءَ ٱللَّٰه</span>
                </div>
              ) : (
                <p>
                  {s.words_missed + s.ayahs_missed + s.jumps} thing
                  {s.words_missed + s.ayahs_missed + s.jumps === 1 ? '' : 's'} to review below —
                  every slip caught is a slip you won't repeat.
                </p>
              )}
            </div>
          </section>

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
              <strong>
                {mins}m {secs}s
              </strong>
              duration
            </div>
          </div>

          {!clean && s.errors.length > 0 && (
            <ul className="error-list">
              {s.errors.map((e, i) => (
                <li key={i}>
                  {e.type === 'MISSED_WORD' && (
                    <>
                      <span className="tag tag-word">WORD</span>
                      Missed word — Ayah {e.payload.ayah}, word {e.payload.position}
                    </>
                  )}
                  {e.type === 'MISSED_AYAH' && (
                    <>
                      <span className="tag tag-ayah">AYAH</span>
                      Ayah {e.payload.ayah} skipped entirely
                    </>
                  )}
                  {e.type === 'MUTASHABEH_JUMP' && (
                    <>
                      <span className="tag tag-jump">JUMP</span>
                      Drifted to Surah {e.payload.dest_surah}, Ayah {e.payload.dest_ayah} — a
                      similar passage
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}

          <div className="summary-actions">
            <button className="primary" onClick={onHome}>
              New Session
            </button>
          </div>
        </>
      )}
    </div>
  )
}

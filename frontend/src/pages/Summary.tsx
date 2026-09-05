import { useEffect, useState } from 'react'
import { api } from '../api'
import { TopBar } from '../components/TopBar'
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
  // words_expected is the server's denominator: correct words plus every word
  // it returned a "missed" verdict on, INCLUDING the words inside a skipped
  // ayah. Deriving one here from words_ok + words_missed is what reported 100%
  // for a recitation that skipped three ayahs of Al-Fatihah.
  const attempted = s?.words_expected ?? 0
  // No recitation captured at all → not "flawless", just empty (the screenshot bug)
  const empty = !s || attempted === 0
  // Repeats do not spoil a recitation, so they never block "flawless". Unplaced
  // audio does: we cannot claim a flawless run over a stretch we never matched.
  const clean =
    s && !empty && s.words_missed === 0 && s.ayahs_missed === 0 && s.jumps === 0 &&
    s.uncertain === 0
  const issues = s ? s.words_missed + s.ayahs_missed + s.jumps : 0
  const pct = s?.accuracy_pct ?? 0
  const mins = s ? Math.floor(s.duration_sec / 60) : 0
  const secs = s ? Math.round(s.duration_sec % 60) : 0

  return (
    <div className="page summary">
      <TopBar onHome={onHome} />
      {!s ? (
        <p style={{ color: 'var(--muted)' }}>Preparing your summary…</p>
      ) : empty ? (
        <section className="summary-hero panel">
          <div className="summary-copy">
            <h2>No recitation captured</h2>
            <p>
              We didn't catch any recitation this session. Make sure your microphone is allowed
              and try again — recite a few words and the tracking begins automatically.
            </p>
            <div className="summary-actions" style={{ marginTop: 16 }}>
              <button className="primary" onClick={onHome}>
                Try Again
              </button>
            </div>
          </div>
        </section>
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
                  {issues} thing
                  {issues === 1 ? '' : 's'} to review below — every slip caught is a slip you
                  won't repeat.
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
            {/* Repeats and unplaced audio are NOT errors and must never be
                styled as such: repeating an ayah is normal recitation, and
                audio we could not place is our uncertainty, not the reciter's
                mistake (P0-4). They are shown because hiding them makes a
                restarted session look identical to a clean one. */}
            {s.repeats > 0 && (
              <div className="stat neutral">
                <strong>{s.repeats}</strong> repeat{s.repeats === 1 ? '' : 's'}
              </div>
            )}
            {s.uncertain > 0 && (
              <div className="stat uncertain">
                <strong>{s.uncertain}</strong> not placed
              </div>
            )}
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

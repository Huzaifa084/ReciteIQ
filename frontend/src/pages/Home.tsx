import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { Logo } from '../components/Logo'
import type { SurahInfo } from '../types'

const MicIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v5a3 3 0 0 0 3 3zm5.6-3a.9.9 0 0 0-1.8.13 3.82 3.82 0 0 1-7.6 0A.9.9 0 0 0 6.4 11a5.62 5.62 0 0 0 4.7 5.46V19H9a.9.9 0 1 0 0 1.8h6A.9.9 0 1 0 15 19h-2.1v-2.54A5.62 5.62 0 0 0 17.6 11z" />
  </svg>
)

export function Home({
  onStart,
  onStartAuto,
}: {
  onStart: (surahs: SurahInfo[], surahId: number, startAyah: number) => void
  onStartAuto: (surahs: SurahInfo[]) => void
}) {
  const [surahs, setSurahs] = useState<SurahInfo[]>([])
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<number | null>(null)
  const [startAyah, setStartAyah] = useState(1)
  const [error, setError] = useState('')

  useEffect(() => {
    api.surahs().then(setSurahs).catch((e) => setError(String(e)))
  }, [])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return surahs
    return surahs.filter(
      (s) =>
        s.name_english.toLowerCase().includes(q) ||
        s.name_arabic.includes(q) ||
        String(s.id) === q,
    )
  }, [surahs, query])

  const sel = surahs.find((s) => s.id === selected)

  return (
    <div className="page home">
      <nav className="nav">
        <Logo />
        <div className="wordmark">
          Recite<span>IQ</span>
        </div>
        <div className="nav-sub">سَمِيعُكَ الذَّكِيّ</div>
      </nav>

      <header className="hero">
        <h1>
          Recite. It listens, tracks
          <br />
          and <span className="accent">corrects — live</span>.
        </h1>
        <p>
          An always-available Sami for your Hifz revision: word-by-word tracking against the
          full Quran, with instant feedback the moment something slips.
        </p>
      </header>

      {error && <div className="error">{error}</div>}

      <section className="cta-card panel">
        <button
          className="mic-button"
          disabled={!surahs.length}
          onClick={() => onStartAuto(surahs)}
          aria-label="Just Recite — start with auto-detection"
        >
          <MicIcon />
        </button>
        <div className="cta-copy">
          <h2>Just Recite</h2>
          <p>
            Start anywhere in the Quran — ReciteIQ <span className="gold">detects the Surah and
            Ayah from your voice</span> within a few words and starts tracking automatically.
          </p>
        </div>
      </section>

      <div className="feature-chips">
        <span className="chip"><b>Missed words</b> flagged in place</span>
        <span className="chip"><b>Skipped ayahs</b> caught instantly</span>
        <span className="chip"><b>Mutashabeh jumps</b> traced to the exact twin verse</span>
      </div>

      <div className="divider">or choose where to start</div>

      <div className="picker-head">
        <input
          type="search"
          placeholder="Search surah by name or number…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {sel && (
          <div className="start-controls">
            <label htmlFor="start-ayah">from Ayah</label>
            <input
              id="start-ayah"
              type="number"
              min={1}
              max={sel.ayah_count}
              value={startAyah}
              onChange={(e) => setStartAyah(Number(e.target.value))}
            />
            <button className="primary" onClick={() => onStart(surahs, sel.id, startAyah)}>
              Start
            </button>
          </div>
        )}
      </div>

      <div className="surah-grid">
        {filtered.map((s) => (
          <button
            key={s.id}
            className={`surah-card ${selected === s.id ? 'selected' : ''}`}
            onClick={() => {
              setSelected(s.id)
              setStartAyah(1)
            }}
          >
            <span className="num">{s.id}</span>
            <span className="names">
              <span className="en">{s.name_english}</span>
              <span className="meta">{s.ayah_count} ayahs</span>
            </span>
            <span className="ar">{s.name_arabic}</span>
          </button>
        ))}
      </div>

      <p className="privacy">
        🔒 Your voice is processed in memory only and never stored — only the text results of your
        session are saved.
      </p>
    </div>
  )
}

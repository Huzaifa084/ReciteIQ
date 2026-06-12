import { useEffect, useState } from 'react'
import { api } from '../api'
import type { SurahInfo } from '../types'

export function Home({
  onStart,
  onStartAuto,
}: {
  onStart: (surahs: SurahInfo[], surahId: number, startAyah: number) => void
  onStartAuto: (surahs: SurahInfo[]) => void
}) {
  const [surahs, setSurahs] = useState<SurahInfo[]>([])
  const [surahId, setSurahId] = useState(1)
  const [startAyah, setStartAyah] = useState(1)
  const [error, setError] = useState('')

  useEffect(() => {
    api.surahs().then(setSurahs).catch((e) => setError(String(e)))
  }, [])

  const selected = surahs.find((s) => s.id === surahId)

  return (
    <div className="page home">
      <h1>
        ReciteIQ <span className="tagline">— your digital Sami</span>
      </h1>
      <p className="intro">
        Select where you want to recite from. ReciteIQ listens and flags missed words, missed
        ayahs, and Mutashabeh jumps in real time.
      </p>
      {error && <div className="error">{error}</div>}
      <div className="auto-start">
        <button className="primary big" disabled={!surahs.length} onClick={() => onStartAuto(surahs)}>
          🎙 Just Recite
        </button>
        <span className="auto-hint">
          Start reciting anywhere — ReciteIQ detects the Surah and Ayah automatically.
        </span>
      </div>
      <div className="divider">or choose manually</div>
      <div className="picker">
        <label>
          Surah
          <select
            value={surahId}
            onChange={(e) => {
              setSurahId(Number(e.target.value))
              setStartAyah(1)
            }}
          >
            {surahs.map((s) => (
              <option key={s.id} value={s.id}>
                {s.id}. {s.name_english} — {s.name_arabic}
              </option>
            ))}
          </select>
        </label>
        <label>
          Starting Ayah
          <input
            type="number"
            min={1}
            max={selected?.ayah_count ?? 1}
            value={startAyah}
            onChange={(e) => setStartAyah(Number(e.target.value))}
          />
        </label>
        <button
          className="primary"
          disabled={!surahs.length}
          onClick={() => onStart(surahs, surahId, startAyah)}
        >
          Start Recitation
        </button>
      </div>
      <p className="privacy">
        🎙 Your voice is processed in memory only and never stored — only the text results of
        your session are saved.
      </p>
    </div>
  )
}

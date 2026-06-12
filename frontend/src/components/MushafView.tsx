/**
 * Renders the reference text with live color state. Global ref idx is derived
 * by enumerating displayed words in order — the backend builds its reference
 * the same way (start ayah -> surah end), so indexes line up by construction.
 */

import { useMemo } from 'react'
import type { DisplayAyah } from '../types'
import type { ReciteState } from '../state/reducer'

const toArabicDigits = (n: number) =>
  String(n).replace(/\d/g, (d) => '٠١٢٣٤٥٦٧٨٩'[Number(d)])

export function MushafView({ ayahs, state }: { ayahs: DisplayAyah[]; state: ReciteState }) {
  const idxOf = useMemo(() => {
    const m = new Map<string, number>()
    let i = 0
    for (const a of ayahs) for (const w of a.words) m.set(`${a.ayah}:${w.position}`, i++)
    return m
  }, [ayahs])

  return (
    <div className="mushaf" dir="rtl">
      {ayahs.map((a) => {
        const ayahMissed = state.missedAyahs.get(a.ayah)
        return (
          <span
            key={a.ayah}
            className={`ayah ${ayahMissed ? `ayah-missed-${ayahMissed}` : ''} ${
              state.position?.ayah === a.ayah ? 'ayah-current' : ''
            }`}
          >
            {a.words.map((w) => {
              const idx = idxOf.get(`${a.ayah}:${w.position}`)!
              const st = state.words.get(idx) ?? 'pending'
              const current = state.position?.idx === idx
              return (
                <span key={w.word_id} className={`word word-${st} ${current ? 'word-current' : ''}`}>
                  {w.text}{' '}
                </span>
              )
            })}
            <span className="ayah-marker">﴿{toArabicDigits(a.ayah)}﴾ </span>
          </span>
        )
      })}
    </div>
  )
}

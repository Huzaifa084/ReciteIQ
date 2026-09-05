/**
 * Renders the reference text with live color state. Global ref idx is derived
 * by enumerating displayed words in order — the backend builds its reference
 * the same way (start ayah -> surah end), so indexes line up by construction.
 *
 * Colour is never the only channel. Around 8% of men cannot reliably separate
 * the red of a missed word from the green of a correct one, and a screen reader
 * gets nothing at all from either, so every word that carries a verdict also
 * carries a written one.
 */

import { useMemo } from 'react'
import type { DisplayAyah, WordStatus } from '../types'
import type { ReciteState } from '../state/reducer'

const toArabicDigits = (n: number) =>
  String(n).replace(/\d/g, (d) => '٠١٢٣٤٥٦٧٨٩'[Number(d)])

/** What each state means, in the words we would use out loud. */
export const WORD_STATUS_LABEL: Record<WordStatus, string | null> = {
  pending: null,
  ok: 'recited correctly',
  uncertain: 'heard, not confirmed — not counted against you',
  'missed-provisional': 'checking',
  missed: 'not heard',
}

export interface WordDetail {
  text: string
  ayah: number
  position: number
  status: WordStatus
}

export function MushafView({
  ayahs,
  state,
  onWordSelect,
  selectedIdx,
}: {
  ayahs: DisplayAyah[]
  state: ReciteState
  onWordSelect?: (detail: WordDetail & { idx: number }) => void
  selectedIdx?: number | null
}) {
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
        const ayahUncertain = !ayahMissed && state.uncertainAyahs.has(a.ayah)
        return (
          <span
            key={a.ayah}
            className={`ayah ${ayahMissed ? `ayah-missed-${ayahMissed}` : ''} ${
              ayahUncertain ? 'ayah-uncertain' : ''
            } ${state.position?.ayah === a.ayah ? 'ayah-current' : ''}`}
          >
            {a.words.map((w) => {
              const idx = idxOf.get(`${a.ayah}:${w.position}`)!
              const st = state.words.get(idx) ?? 'pending'
              const current = state.position?.idx === idx
              const label = WORD_STATUS_LABEL[st]
              // Only a word carrying a verdict is worth stopping on. Making every
              // word focusable would bury the few that matter in hundreds of tabs.
              const inspectable = st === 'missed' || st === 'uncertain' || st === 'missed-provisional'
              return (
                <span
                  key={w.word_id}
                  className={`word word-${st} ${current ? 'word-current' : ''} ${
                    selectedIdx === idx ? 'word-selected' : ''
                  }`}
                  {...(label
                    ? { 'aria-label': `${w.text} — ayah ${a.ayah}, word ${w.position}, ${label}` }
                    : {})}
                  {...(inspectable && onWordSelect
                    ? {
                        role: 'button',
                        tabIndex: 0,
                        onClick: () =>
                          onWordSelect({ idx, text: w.text, ayah: a.ayah, position: w.position, status: st }),
                        onKeyDown: (e: React.KeyboardEvent) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault()
                            onWordSelect({ idx, text: w.text, ayah: a.ayah, position: w.position, status: st })
                          }
                        },
                      }
                    : {})}
                >
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

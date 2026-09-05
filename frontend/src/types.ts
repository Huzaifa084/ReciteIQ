export interface SurahInfo {
  id: number
  name_arabic: string
  name_english: string
  ayah_count: number
}

export interface DisplayWord {
  word_id: number
  position: number
  text: string
}

export interface DisplayAyah {
  ayah: number
  verse_key: string
  words: DisplayWord[]
}

export type EventState = 'provisional' | 'confirmed' | 'revoked'

export interface RIQEvent {
  event_id: number
  type:
    | 'WORD_OK'
    | 'MISSED_WORD'
    | 'MISSED_AYAH'
    | 'MUTASHABEH_JUMP'
    | 'REPEAT'
    | 'PREAMBLE'
    | 'POSITION'
    | 'UNCERTAIN'
  state: EventState
  payload: Record<string, any>
  refers_to?: number
}

export type WordStatus = 'pending' | 'ok' | 'uncertain' | 'missed-provisional' | 'missed'

/** Heard but unplaceable — our uncertainty, never a verdict on the reciter. */
export type AyahUncertainty = 'provisional'

export interface JumpAlert {
  eventId: number
  state: EventState
  destSurah: number
  destAyah: number
  score: number
}

export interface SessionSummaryData {
  duration_sec: number
  words_ok: number
  words_missed: number
  ayahs_missed: number
  jumps: number
  /** Benign, never counted as errors — see the note in Summary.tsx. */
  repeats: number
  uncertain: number
  /** Accuracy comes from the server. Do NOT recompute it here: a denominator
   *  built from words_ok + words_missed omits every word inside a skipped
   *  ayah, which reported 100% for a recitation that skipped three. */
  words_expected: number
  accuracy_pct: number | null
  errors: Record<string, any>[]
}

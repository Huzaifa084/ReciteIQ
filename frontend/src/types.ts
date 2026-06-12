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
  state: EventState
  payload: Record<string, any>
  refers_to?: number
}

export type WordStatus = 'pending' | 'ok' | 'missed-provisional' | 'missed'

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
  errors: Record<string, any>[]
}

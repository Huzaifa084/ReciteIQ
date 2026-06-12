/**
 * Event reducer — applies the provisional/confirmed/revoked lifecycle (D13)
 * to per-word UI state. Keyed by global ref idx from event payloads.
 */

import type { JumpAlert, RIQEvent, WordStatus } from '../types'

export interface ReciteState {
  words: Map<number, WordStatus>          // ref idx -> status
  missedAyahs: Map<number, 'provisional' | 'confirmed'>  // ayah number -> state
  jump: JumpAlert | null
  position: { surah: number; ayah: number; idx: number } | null
  provisionalIndex: Map<number, number>   // event_id -> ref idx (for revocation)
}

export const initialState = (): ReciteState => ({
  words: new Map(),
  missedAyahs: new Map(),
  jump: null,
  position: null,
  provisionalIndex: new Map(),
})

export function applyEvents(prev: ReciteState, events: RIQEvent[]): ReciteState {
  const s: ReciteState = {
    words: new Map(prev.words),
    missedAyahs: new Map(prev.missedAyahs),
    jump: prev.jump,
    position: prev.position,
    provisionalIndex: new Map(prev.provisionalIndex),
  }
  for (const e of events) {
    const idx = e.payload.idx as number | undefined
    switch (e.type) {
      case 'WORD_OK':
        if (idx !== undefined) s.words.set(idx, 'ok')
        break
      case 'MISSED_WORD':
        if (e.state === 'provisional' && idx !== undefined) {
          s.words.set(idx, 'missed-provisional')
          s.provisionalIndex.set(e.event_id, idx)
        } else if (e.state === 'confirmed' && idx !== undefined) {
          s.words.set(idx, 'missed')
        } else if (e.state === 'revoked' && e.refers_to !== undefined) {
          const ridx = s.provisionalIndex.get(e.refers_to)
          if (ridx !== undefined && s.words.get(ridx) === 'missed-provisional') {
            s.words.delete(ridx)
          }
        }
        break
      case 'MISSED_AYAH': {
        const ayah = e.payload.ayah as number
        if (e.state === 'revoked') s.missedAyahs.delete(ayah)
        else s.missedAyahs.set(ayah, e.state as 'provisional' | 'confirmed')
        break
      }
      case 'MUTASHABEH_JUMP':
        if (e.state === 'revoked') {
          if (s.jump && s.jump.eventId === e.refers_to) s.jump = null
        } else {
          s.jump = {
            eventId: e.event_id,
            state: e.state,
            destSurah: e.payload.dest_surah,
            destAyah: e.payload.dest_ayah,
            score: e.payload.score,
          }
        }
        break
      case 'POSITION':
        s.position = { surah: e.payload.surah, ayah: e.payload.ayah, idx: e.payload.idx }
        break
      case 'REPEAT':
        // benign: clear provisional misses at/after the rewound point
        if (idx !== undefined) {
          for (const [widx, st] of s.words) {
            if (widx > idx && st === 'missed-provisional') s.words.delete(widx)
          }
        }
        break
    }
  }
  return s
}

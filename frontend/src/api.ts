import type { DisplayAyah, SessionSummaryData, SurahInfo } from './types'

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

export const api = {
  surahs: (): Promise<SurahInfo[]> => fetch('/api/surahs').then((r) => json(r)),

  surahText: (surahId: number, startAyah: number): Promise<DisplayAyah[]> =>
    fetch(`/api/surahs/${surahId}/text?start_ayah=${startAyah}`).then((r) => json(r)),

  createSession: (surahId: number, startAyah: number): Promise<{ session_id: string }> =>
    fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ surah_id: surahId, start_ayah: startAyah }),
    }).then((r) => json(r)),

  endSession: (sessionId: string): Promise<void> =>
    fetch(`/api/sessions/${sessionId}/end`, { method: 'POST' }).then(() => undefined),

  summary: (
    sessionId: string,
  ): Promise<{ status: string; surah_id: number; summary: SessionSummaryData | null }> =>
    fetch(`/api/sessions/${sessionId}/summary`).then((r) => json(r)),
}

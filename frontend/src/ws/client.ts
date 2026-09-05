/**
 * WS client with auto-reconnect + resume (D9): on reconnect we echo the last
 * confirmed reference index so the backend rehydrates the tracker in place.
 */

import type { RIQEvent } from '../types'

export interface WSCallbacks {
  onEvents: (events: RIQEvent[]) => void
  onEnded: (reason: string) => void
  onRejected: (reason: string) => void
  onStatusChange: (s: 'connecting' | 'open' | 'closed' | 'reconnecting' | 'lost') => void
  /** Auto-detect resolved: the backend locked onto this location. */
  onDetected?: (surah: number, ayah: number) => void
  /** Backend heard audio but could not place it (P0-4). */
  onNoMatch?: (info: { c_ctc: number | null; closest_cer: number | null; run: number }) => void
  /** Audio is being heard but the window has not closed yet — no verdict implied. */
  onBuffering?: (info: { bufferedSec: number; inSilence: boolean }) => void
}

const MAX_RECONNECTS = 5

export class SessionSocket {
  private ws: WebSocket | null = null
  private closedByUs = false
  private reconnectAttempts = 0
  lastConfirmedIdx = 0

  private sessionId: string
  private cb: WSCallbacks

  constructor(sessionId: string, cb: WSCallbacks) {
    this.sessionId = sessionId
    this.cb = cb
  }

  connect(): void {
    this.cb.onStatusChange('connecting')
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    this.ws = new WebSocket(`${proto}://${location.host}/ws/session/${this.sessionId}`)
    this.ws.binaryType = 'arraybuffer'

    this.ws.onopen = () => {
      this.reconnectAttempts = 0
      this.cb.onStatusChange('open')
      // tell the backend which capture mode this take used, so the per-window
      // diagnostics can be correlated when A/B-ing ?rawaudio=1
      this.ws!.send(JSON.stringify({
        type: 'client_info',
        raw_audio: new URLSearchParams(location.search).get('rawaudio') === '1',
      }))
      if (this.lastConfirmedIdx > 0) {
        this.ws!.send(JSON.stringify({ type: 'resume', idx: this.lastConfirmedIdx }))
      }
    }

    this.ws.onmessage = (e) => {
      const msg = JSON.parse(e.data)
      if (msg.type === 'events') {
        for (const ev of msg.events as RIQEvent[]) {
          if (ev.type === 'WORD_OK' && ev.state === 'confirmed') {
            this.lastConfirmedIdx = Math.max(this.lastConfirmedIdx, (ev.payload.idx ?? 0) + 1)
          }
        }
        this.cb.onEvents(msg.events)
      } else if (msg.type === 'detected') {
        this.cb.onDetected?.(msg.surah, msg.ayah)
      } else if (msg.type === 'buffering') {
        this.cb.onBuffering?.({ bufferedSec: msg.buffered_sec ?? 0, inSilence: !!msg.in_silence })
      } else if (msg.type === 'no_match') {
        this.cb.onNoMatch?.({ c_ctc: msg.c_ctc ?? null, closest_cer: msg.closest_cer ?? null, run: msg.run ?? 1 })
      } else if (msg.type === 'ended') {
        this.closedByUs = true
        this.cb.onEnded(msg.reason)
      } else if (msg.type === 'rejected') {
        this.closedByUs = true
        this.cb.onRejected(msg.reason)
      }
    }

    this.ws.onclose = () => {
      if (this.closedByUs) {
        this.cb.onStatusChange('closed')
        return
      }
      if (this.reconnectAttempts < MAX_RECONNECTS) {
        const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 8000)
        this.reconnectAttempts++
        // Say so. Silence here meant the reciter carried on into a dead socket
        // and only found out at the summary.
        this.cb.onStatusChange('reconnecting')
        setTimeout(() => this.connect(), delay)
      } else {
        this.cb.onStatusChange('lost')
      }
    }
  }

  sendAudio(pcm: ArrayBuffer): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(pcm)
  }

  reposition(idx: number): void {
    this.ws?.send(JSON.stringify({ type: 'reposition', idx }))
  }

  end(): void {
    this.closedByUs = true
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: 'end' }))
  }

  close(): void {
    this.closedByUs = true
    this.ws?.close()
  }
}

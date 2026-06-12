/**
 * WS client with auto-reconnect + resume (D9): on reconnect we echo the last
 * confirmed reference index so the backend rehydrates the tracker in place.
 */

import type { RIQEvent } from '../types'

export interface WSCallbacks {
  onEvents: (events: RIQEvent[]) => void
  onEnded: (reason: string) => void
  onRejected: (reason: string) => void
  onStatusChange: (s: 'connecting' | 'open' | 'closed') => void
}

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
      } else if (msg.type === 'ended') {
        this.closedByUs = true
        this.cb.onEnded(msg.reason)
      } else if (msg.type === 'rejected') {
        this.closedByUs = true
        this.cb.onRejected(msg.reason)
      }
    }

    this.ws.onclose = () => {
      this.cb.onStatusChange('closed')
      if (!this.closedByUs && this.reconnectAttempts < 5) {
        const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 8000)
        this.reconnectAttempts++
        setTimeout(() => this.connect(), delay)
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

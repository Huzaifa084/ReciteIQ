/**
 * Mic capture -> 16kHz mono s16le PCM chunks (the WS audio contract).
 *
 * Browsers won't reliably honor a 16kHz AudioContext, so we capture at the
 * device rate via an AudioWorklet and linearly resample to 16k here.
 * Audio is never persisted anywhere — it flows straight to the WS (privacy D10).
 */

const TARGET_RATE = 16000
const CHUNK_MS = 250

const workletSource = `
class CaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0]?.[0]
    if (ch) this.port.postMessage(ch.slice(0))
    return true
  }
}
registerProcessor('riq-capture', CaptureProcessor)
`

export class Recorder {
  private ctx: AudioContext | null = null
  private stream: MediaStream | null = null
  private node: AudioWorkletNode | null = null
  private buf: number[] = []
  rawAudio = false          // true when ?rawaudio=1 disabled WebRTC processing
  private chunkSamples = (TARGET_RATE * CHUNK_MS) / 1000

  async start(onChunk: (pcm: ArrayBuffer) => void, onLevel?: (rms: number) => void): Promise<void> {
    // WebRTC voice processing is tuned for telephony intelligibility, not for
    // phoneme recognition: noise suppression gates spectrally, AEC applies
    // nonlinear processing, and AGC pumps the level. All three can smear the
    // sustained vowels (madd) that Quranic recitation is full of.
    //
    // Measured motivation: the SAME voice reciting the SAME surah scores CER
    // 0.185-0.407 (7/7 ayahs) from a file recorded outside the browser, but
    // 0.375-1.00 through this path with comparable window sizes and healthy
    // level — so the gap is not segmentation. `?rawaudio=1` turns the processing
    // off so the two can be A/B'd in one sitting.
    const raw = new URLSearchParams(location.search).get('rawaudio') === '1'
    this.rawAudio = raw
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: raw
        ? {
            channelCount: 1,
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false,
          }
        : { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    })
    this.ctx = new AudioContext()
    const url = URL.createObjectURL(new Blob([workletSource], { type: 'application/javascript' }))
    await this.ctx.audioWorklet.addModule(url)
    URL.revokeObjectURL(url)

    const src = this.ctx.createMediaStreamSource(this.stream)
    this.node = new AudioWorkletNode(this.ctx, 'riq-capture')
    const ratio = this.ctx.sampleRate / TARGET_RATE

    this.node.port.onmessage = (e: MessageEvent<Float32Array>) => {
      const input = e.data
      // linear resample device-rate -> 16k
      const outLen = Math.floor(input.length / ratio)
      for (let i = 0; i < outLen; i++) {
        const pos = i * ratio
        const i0 = Math.floor(pos)
        const frac = pos - i0
        const s = input[i0] * (1 - frac) + (input[Math.min(i0 + 1, input.length - 1)] ?? 0) * frac
        this.buf.push(s)
      }
      while (this.buf.length >= this.chunkSamples) {
        const chunk = this.buf.splice(0, this.chunkSamples)
        const pcm = new Int16Array(chunk.length)
        let sumSq = 0
        for (let i = 0; i < chunk.length; i++) {
          pcm[i] = Math.max(-32768, Math.min(32767, Math.round(chunk[i] * 32767)))
          sumSq += chunk[i] * chunk[i]
        }
        onChunk(pcm.buffer)
        onLevel?.(Math.sqrt(sumSq / chunk.length)) // RMS 0..~0.5, drives the voice ring
      }
    }
    src.connect(this.node)
  }

  stop(): void {
    this.node?.disconnect()
    this.stream?.getTracks().forEach((t) => t.stop())
    this.ctx?.close()
    this.node = null
    this.stream = null
    this.ctx = null
    this.buf = []
  }
}

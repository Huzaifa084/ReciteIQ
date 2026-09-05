import type { JumpAlert, SurahInfo } from '../types'

/**
 * Mutashabeh drift: the reciter has continued into a passage that reads almost
 * identically to the one they were in. This is among the most understandable
 * slips in Hifz — the two texts really are near-identical — so the banner
 * informs and offers a choice rather than raising an alarm. It used to open
 * with a warning glyph and the word "detected", which reads like an accusation
 * for something the Qur'an's own structure invites.
 */
export function JumpBanner({
  jump,
  surahs,
  from,
  onContinueHere,
  onDismiss,
}: {
  jump: JumpAlert
  surahs: SurahInfo[]
  from?: { surah: number; ayah: number } | null
  onContinueHere: () => void
  onDismiss: () => void
}) {
  const dest = surahs.find((s) => s.id === jump.destSurah)
  const fromName = from ? surahs.find((s) => s.id === from.surah)?.name_english : undefined
  const confirmed = jump.state === 'confirmed'

  return (
    <div
      className={`jump-banner ${confirmed ? 'jump-confirmed' : 'jump-provisional'}`}
      role={confirmed ? 'alert' : 'status'}
    >
      <div className="jump-text">
        {confirmed ? (
          <>
            <strong>You've moved to a similar passage.</strong>{' '}
            {dest ? dest.name_english : `Surah ${jump.destSurah}`}, ayah {jump.destAyah}
            {from && fromName ? (
              <> — you were in {fromName}, ayah {from.ayah}.</>
            ) : (
              '.'
            )}{' '}
            <span className="jump-why">
              These two passages read almost the same, which is exactly why they are
              easy to cross.
            </span>
          </>
        ) : (
          <>Listening — this may be a similar passage…</>
        )}
      </div>
      {confirmed && (
        <div className="jump-actions">
          <button onClick={onContinueHere}>Continue from here</button>
          <button className="secondary" onClick={onDismiss}>
            I'll go back myself
          </button>
        </div>
      )}
    </div>
  )
}

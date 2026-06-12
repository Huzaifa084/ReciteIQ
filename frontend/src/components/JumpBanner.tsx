import type { JumpAlert, SurahInfo } from '../types'

export function JumpBanner({
  jump,
  surahs,
  onContinueHere,
  onDismiss,
}: {
  jump: JumpAlert
  surahs: SurahInfo[]
  onContinueHere: () => void
  onDismiss: () => void
}) {
  const dest = surahs.find((s) => s.id === jump.destSurah)
  const confirmed = jump.state === 'confirmed'
  return (
    <div className={`jump-banner ${confirmed ? 'jump-confirmed' : 'jump-provisional'}`}>
      <div className="jump-text">
        {confirmed ? '⚠ Mutashabeh jump detected' : 'Possible Mutashabeh jump…'}
        <strong>
          {' '}
          → {dest ? `${dest.name_english} (${dest.name_arabic})` : `Surah ${jump.destSurah}`},
          Ayah {jump.destAyah}
        </strong>
      </div>
      {confirmed && (
        <div className="jump-actions">
          <button onClick={onContinueHere}>Continue from there</button>
          <button className="secondary" onClick={onDismiss}>
            I'll go back
          </button>
        </div>
      )}
    </div>
  )
}

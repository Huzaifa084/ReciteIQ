import { Logo } from './Logo'

/** Persistent top bar for in-session pages. The wordmark is a Home button;
 * on the recite page it ends the session (Recite unmounts and tears down). */
export function TopBar({ onHome, confirmLeave }: { onHome: () => void; confirmLeave?: boolean }) {
  const go = () => {
    if (confirmLeave && !window.confirm('Leave this session and return home?')) return
    onHome()
  }
  return (
    <nav className="nav">
      <button className="brand-button" onClick={go} aria-label="Back to home">
        <Logo size={32} />
        <span className="wordmark">
          Recite<span>IQ</span>
        </span>
      </button>
      <button className="home-link" onClick={go}>
        ← Home
      </button>
    </nav>
  )
}

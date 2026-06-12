import { useState } from 'react'
import { Home } from './pages/Home'
import { Recite } from './pages/Recite'
import { Summary } from './pages/Summary'
import type { SurahInfo } from './types'

type Page =
  | { name: 'home' }
  | { name: 'recite'; surahId: number | null; startAyah: number; auto?: boolean }
  | { name: 'summary'; sessionId: string }

export default function App() {
  const [page, setPage] = useState<Page>({ name: 'home' })
  const [surahs, setSurahs] = useState<SurahInfo[]>([])

  return (
    <div className="app">
      {page.name === 'home' && (
        <Home
          onStart={(list, surahId, startAyah) => {
            setSurahs(list)
            setPage({ name: 'recite', surahId, startAyah })
          }}
          onStartAuto={(list) => {
            setSurahs(list)
            setPage({ name: 'recite', surahId: null, startAyah: 1, auto: true })
          }}
        />
      )}
      {page.name === 'recite' && (
        <Recite
          surahs={surahs}
          surahId={page.surahId}
          startAyah={page.startAyah}
          auto={page.auto}
          onFinished={(sessionId) => setPage({ name: 'summary', sessionId })}
          onJumpAccepted={(destSurah, destAyah) =>
            setPage({ name: 'recite', surahId: destSurah, startAyah: destAyah })
          }
        />
      )}
      {page.name === 'summary' && (
        <Summary
          sessionId={page.sessionId}
          surahs={surahs}
          onHome={() => setPage({ name: 'home' })}
        />
      )}
    </div>
  )
}

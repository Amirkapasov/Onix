import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import 'leaflet/dist/leaflet.css'
import './index.css'
import App from './App'

// ?static=1 — скриншоты headless-браузером: без анимаций появления.
if (new URLSearchParams(window.location.search).get('static') === '1') document.documentElement.classList.add('static')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

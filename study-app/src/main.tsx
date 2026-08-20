import React from 'react'
import ReactDOM from 'react-dom/client'

import App from './App'
import './i18n'
// Order matters: Tailwind's preflight first, then the design tokens, so a
// token always beats the reset (see index.css).
import './index.css'
import './tokens.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

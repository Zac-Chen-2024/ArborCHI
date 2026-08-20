import js from '@eslint/js'
import i18next from 'eslint-plugin-i18next'
import reactHooks from 'eslint-plugin-react-hooks'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: { ecmaVersion: 2022, globals: globals.browser },
    plugins: { 'react-hooks': reactHooks, i18next },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // FS-03: any bare UI string in JSX is a review reject. Everything a
      // participant can read goes through i18n; a hard-coded label would ship
      // one language into a session configured for the other.
      'i18next/no-literal-string': [
        'error',
        {
          markupOnly: true,
          // Symbols and punctuation are not translatable content.
          ignore: ['⠿', '⋯', '›', '−', '＋', 'p.', '%', '—', 'seq ', 'OK'],
          ignoreAttribute: ['className', 'style', 'data-sub', 'data-state', 'id', 'role', 'viewBox', 'd', 'fill', 'stroke'],
        },
      ],
    },
  },
)

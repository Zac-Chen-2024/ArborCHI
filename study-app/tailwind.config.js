/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  // No theme extension on purpose: the mockups are the visual source of truth
  // and every shared dimension lives in tokens.css (红线 #9). Tailwind here is
  // only the utility vocabulary the mockups already speak.
  theme: { extend: {} },
  plugins: [],
}

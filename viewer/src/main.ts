import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

window.onerror = (msg, url, line, col, err) => {
  console.error('[global onerror]', msg, url, line, col, err)
}
window.addEventListener('unhandledrejection', (e) => {
  console.error('[unhandledrejection]', e.reason, e.promise)
})

createApp(App).mount('#app')

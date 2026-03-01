import { createApp } from 'vue'
import App from './App.vue'
import './style.css'
import { logger } from './lib/logger'

logger.info('App', 'Запуск 3D Viewer')

window.onerror = (msg, url, line, col, err) => {
  const detail = [url, line, col].filter(Boolean).join(':')
  logger.error('Global', `onerror ${String(msg)} ${detail}`, err)
}
window.addEventListener('unhandledrejection', (e) => {
  logger.error('Global', 'unhandledrejection', e.reason)
})

createApp(App).mount('#app')
logger.info('App', 'Приложение запущено')
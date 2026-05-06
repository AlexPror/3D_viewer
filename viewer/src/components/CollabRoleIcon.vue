<script setup lang="ts">
/** Соответствует slug ролей в API / чате */
export type CollabRoleSlug =
  | 'gip'
  | 'chief_designer'
  | 'designer'
  | 'installer'
  | 'assembler'
  | 'client'

defineProps<{
  role: CollabRoleSlug
  /** CSS size e.g. 14px */
  size?: string | number
}>()
</script>

<template>
  <svg
    class="collab-role-icon"
    :width="size ?? 16"
    :height="size ?? 16"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.6"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <!-- ГИП: документ проекта -->
    <g v-if="role === 'gip'" fill="none">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
      <path d="M9 13h6" />
      <path d="M9 17h4" />
    </g>
    <!-- Главный конструктор: сетка / координация -->
    <g v-else-if="role === 'chief_designer'" fill="none">
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </g>
    <!-- Конструктор: карандаш / чертёж -->
    <g v-else-if="role === 'designer'" fill="none">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5" />
    </g>
    <!-- Монтажник: ключ -->
    <g v-else-if="role === 'installer'" fill="none">
      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76Z" />
    </g>
    <!-- Сборщик: куб / модуль -->
    <g v-else-if="role === 'assembler'" fill="none">
      <path d="M12 2 3 7v10l9 5 9-5V7l-9-5Z" />
      <path d="M3 7 12 12l9-5" />
      <path d="M12 22V12" />
    </g>
    <!-- Клиент: пользователь -->
    <g v-else fill="none">
      <path d="M19 21a7 7 0 1 0-14 0" />
      <circle cx="12" cy="7" r="4" />
    </g>
  </svg>
</template>

<style scoped>
.collab-role-icon {
  flex-shrink: 0;
  display: block;
  opacity: 0.95;
}
</style>

<script setup lang="ts">
defineProps<{ name: 'tree' | 'params' | 'layers' | 'library' }>()
</script>

<template>
  <svg class="viewer-tab-icon" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
    <template v-if="name === 'tree'">
      <path fill="currentColor" d="M4 3h4v4H4V3zm0 6h4v4H4V9zm0 6h4v4H4v-4zm6-12h6v3h-6V3zm0 5h6v3h-6V8zm0 5h6v3h-6v-3z" opacity="0.35" />
      <path fill="currentColor" d="M3 2h5v5H3V2zm0 7h5v5H3V9zm0 7h5v5H3v-5zm8-8h6v2H11V8zm0 4h4v2h-4v-2z" />
    </template>
    <template v-else-if="name === 'params'">
      <path
        fill="currentColor"
        d="M10 2a1.2 1.2 0 0 1 1.15.86l.08.35 1.02.4a1.2 1.2 0 0 1 .65 1.57l-.2.5-.2.5a1.2 1.2 0 0 1 1.57.65l.4 1.02.35.08A1.2 1.2 0 0 1 18 10a1.2 1.2 0 0 1-.86 1.15l-.35.08-.4 1.02a1.2 1.2 0 0 1-1.57.65l-.5-.2-.5-.2a1.2 1.2 0 0 1-.65 1.57l-1.02.4-.08.35A1.2 1.2 0 0 1 10 18a1.2 1.2 0 0 1-1.15-.86l-.08-.35-1.02-.4a1.2 1.2 0 0 1-.65-1.57l.2-.5.2-.5a1.2 1.2 0 0 1-1.57-.65l-.4-1.02-.35-.08A1.2 1.2 0 0 1 2 10a1.2 1.2 0 0 1 .86-1.15l.35-.08.4-1.02a1.2 1.2 0 0 1 1.57-.65l.5.2.5.2a1.2 1.2 0 0 1 .65-1.57l1.02-.4.08-.35A1.2 1.2 0 0 1 10 2zm0 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8z"
      />
    </template>
    <template v-else-if="name === 'layers'">
      <path fill="currentColor" d="M10 2 3 6l7 4 7-4-7-4zm0 6L3 12l7 4 7-4-7-4zm0 6L3 18l7 4 7-4-7-4z" opacity="0.45" />
      <path fill="currentColor" d="M10 3 5 6l5 3 5-3-5-3zm0 5L5 11l5 3 5-3-5-3z" />
    </template>
    <template v-else>
      <path fill="currentColor" d="M4 3h12v2H4V3zm0 4h10v2H4V7zm0 4h12v2H4v-2zm0 4h8v2H4v-2z" />
      <rect fill="currentColor" x="14" y="13" width="3" height="5" rx="0.5" opacity="0.5" />
    </template>
  </svg>
</template>

<style scoped>
.viewer-tab-icon {
  width: 1.05rem;
  height: 1.05rem;
  display: block;
}
</style>

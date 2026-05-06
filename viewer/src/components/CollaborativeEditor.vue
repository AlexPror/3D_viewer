<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, shallowRef, nextTick } from 'vue'
import * as Y from 'yjs'
import type { Awareness } from 'y-protocols/awareness'
import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { basicSetup } from 'codemirror'
import { oneDark } from '@codemirror/theme-one-dark'
import { yCollab } from 'y-codemirror.next'

const props = defineProps<{
  yDoc: Y.Doc
  awareness: Awareness
}>()

const host = ref<HTMLElement | null>(null)
const viewRef = shallowRef<EditorView | null>(null)

function mountEditor() {
  const el = host.value
  if (!el) return
  viewRef.value?.destroy()
  viewRef.value = null
  const ytext = props.yDoc.getText('project-notes')
  const state = EditorState.create({
    doc: ytext.toString(),
    extensions: [
      basicSetup,
      oneDark,
      yCollab(ytext, props.awareness, { undoManager: false }),
      EditorView.theme({
        '&': { height: '100%' },
        '.cm-editor': { height: '100%' },
        '.cm-scroller': { overflow: 'auto' },
      }),
    ],
  })
  viewRef.value = new EditorView({ state, parent: el })
}

onMounted(() => {
  mountEditor()
})

watch(
  () => props.yDoc,
  () => {
    nextTick(() => mountEditor())
  }
)

onUnmounted(() => {
  viewRef.value?.destroy()
  viewRef.value = null
})
</script>

<template>
  <div ref="host" class="collab-cm-host" />
</template>

<style scoped>
.collab-cm-host {
  flex: 1;
  min-height: 120px;
  min-width: 0;
}
.collab-cm-host :deep(.cm-editor) {
  border-radius: 6px;
  border: 1px solid #3a5280;
}
</style>

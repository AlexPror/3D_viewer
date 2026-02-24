<script setup lang="ts">
import { ref } from 'vue'
import Viewer3D from './components/Viewer3D.vue'
import ViewerToolbar from './components/ViewerToolbar.vue'
import ScreenshotEditorModal from './components/ScreenshotEditorModal.vue'

const viewerRef = ref<InstanceType<typeof Viewer3D> | null>(null)
const screenshotImageUrl = ref<string | null>(null)
const screenshotSuggestedFileName = ref<string | null>(null)
const showScreenshotModal = ref(false)

function onOpenFile() {
  viewerRef.value?.openFileDialog()
}

function onResetView() {
  viewerRef.value?.resetView?.()
}

async function onScreenshot() {
  const url = await viewerRef.value?.takeScreenshot()
  if (url) {
    screenshotImageUrl.value = url
    screenshotSuggestedFileName.value = viewerRef.value?.getLoadedFileName?.() ?? null
    showScreenshotModal.value = true
  }
}

function closeScreenshotModal() {
  showScreenshotModal.value = false
  screenshotImageUrl.value = null
  screenshotSuggestedFileName.value = null
}
</script>

<template>
  <div class="app">
    <ViewerToolbar
      @open-file="onOpenFile"
      @reset-view="onResetView"
      @screenshot="onScreenshot"
    />
    <Viewer3D ref="viewerRef" />
    <ScreenshotEditorModal
      v-if="showScreenshotModal && screenshotImageUrl"
      :image-url="screenshotImageUrl!"
      :suggested-file-name="screenshotSuggestedFileName"
      @close="closeScreenshotModal"
    />
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}
</style>

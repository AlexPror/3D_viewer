<script setup lang="ts">
import YandexDiskTree from './YandexDiskTree.vue'

export type DiskNode = {
  type: 'dir' | 'file'
  name: string
  path: string
  href?: string | null
  mime_type?: string | null
  size?: number | null
  children?: DiskNode[]
  expanded?: boolean
  loaded?: boolean
  loading?: boolean
}

const props = defineProps<{
  nodes: DiskNode[]
  tab: 'pdf' | '3d'
  showFile: (name: string) => boolean
}>()

const emit = defineEmits<{
  toggleDir: [node: DiskNode]
}>()

function visibleNodes(list: DiskNode[]): DiskNode[] {
  return list.filter((n) => n.type === 'dir' || props.showFile(n.name))
}
</script>

<template>
  <div class="ide-tree-entries">
    <template v-for="node in visibleNodes(nodes)" :key="node.path || node.name">
      <template v-if="node.type === 'dir'">
        <button
          type="button"
          class="ide-tree-row ide-tree-row--folder"
          :aria-expanded="node.expanded ? 'true' : 'false'"
          @click="emit('toggleDir', node)"
        >
          <span class="ide-tree-chevron">{{ node.expanded ? '▼' : '▶' }}</span>
          <span class="ide-tree-icon" aria-hidden="true">📁</span>
          <span class="ide-tree-label">{{ node.name || node.path || '…' }}</span>
          <span v-if="node.loading" class="ide-tree-loading">…</span>
        </button>
        <div v-show="node.expanded" class="ide-tree-children">
          <YandexDiskTree
            v-if="node.children && node.children.length"
            :nodes="node.children"
            :tab="tab"
            :show-file="showFile"
            @toggle-dir="emit('toggleDir', $event)"
          />
          <div v-else-if="node.loaded && !node.children?.length" class="ide-tree-empty-branch">пусто</div>
        </div>
      </template>
      <div v-else class="ide-tree-row ide-tree-row--file">
        <span class="ide-tree-chevron ide-tree-chevron--spacer" aria-hidden="true" />
        <span class="ide-tree-icon" aria-hidden="true">📄</span>
        <a
          v-if="node.href"
          class="ide-tree-label ide-tree-file-link"
          :href="node.href"
          target="_blank"
          rel="noopener noreferrer"
        >
          {{ node.name }}
        </a>
        <span v-else class="ide-tree-label">{{ node.name }}</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.ide-tree-entries {
  display: flex;
  flex-direction: column;
  align-items: stretch;
}
.ide-tree-loading {
  margin-left: 0.35rem;
  opacity: 0.6;
  font-size: 0.75rem;
}
.ide-tree-empty-branch {
  padding: 0.15rem 0 0.35rem 1.5rem;
  font-size: 0.75rem;
  opacity: 0.55;
}
.ide-tree-file-link {
  color: inherit;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.ide-tree-file-link:hover {
  opacity: 0.92;
}
</style>

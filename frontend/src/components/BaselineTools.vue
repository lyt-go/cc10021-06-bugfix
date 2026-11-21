<template>
  <section v-if="meta.key === 'column_profile'" class="baseline-tools" data-testid="column-profile-entry">
    <header class="tools-head">
      <h3>字段画像入口 · 空值率偏离核对</h3>
      <p class="tools-desc">
        输入带单位的读数回查画像基线，比较结果按校验凭证保存；
        重取画像时按凭证还原当次使用的基线版本。
      </p>
    </header>

    <form class="tools-form" @submit.prevent="runCheck">
      <label>
        <span>目标表名</span>
        <input v-model="form.tableName" data-testid="null-rate-table" placeholder="如 dwd_order" required />
      </label>
      <label>
        <span>空值率读数</span>
        <input v-model="form.nullRate" data-testid="null-rate-value" placeholder="如 15%" required />
      </label>
      <label>
        <span>读数口径（可选）</span>
        <select v-model="form.unit" data-testid="null-rate-unit">
          <option value="">按数值单位判断</option>
          <option value="%">百分数</option>
          <option value="比例">比例（0.15）</option>
          <option value="原始值">原始值</option>
        </select>
      </label>
      <button class="btn primary" data-testid="run-null-rate" type="submit" :disabled="loading">
        {{ loading ? '校验中…' : '校验空值率' }}
      </button>
    </form>

    <aside v-if="errorMessage" class="tools-error" data-testid="null-rate-error">{{ errorMessage }}</aside>

    <BaselineComparisonPanel
      v-if="comparison"
      :comparison="comparison"
      data-testid="null-rate-result"
    />
  </section>

  <section v-else-if="meta.key === 'dq_incident'" class="baseline-tools" data-testid="incident-review-entry">
    <header class="tools-head">
      <h3>事件复核面板 · 基线比较复核</h3>
      <p class="tools-desc">
        按校验凭证或事件编号读取当时的基线比较明细，复核不重新计算当前基线。
      </p>
    </header>

    <form class="tools-form" @submit.prevent="runReview">
      <label>
        <span>校验凭证 / 事件编号</span>
        <input v-model="reviewRef" data-testid="review-reference" placeholder="如 BC-0001 或 DQ_I-0004" required />
      </label>
      <button class="btn primary" data-testid="run-review" type="submit" :disabled="loading">
        {{ loading ? '读取中…' : '复核事件' }}
      </button>
    </form>

    <aside v-if="errorMessage" class="tools-error" data-testid="review-error">{{ errorMessage }}</aside>
    <BaselineComparisonPanel
      v-if="comparison"
      :comparison="comparison"
      data-testid="review-result"
    />
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'

import { checkNullRate, loadIncidentReview } from '@/api/backend-service'
import BaselineComparisonPanel from '@/components/BaselineComparisonPanel.vue'
import type { BaselineComparison } from '@/data/baseline'
import { moduleMeta } from '@/data/modules'

const props = defineProps<{ moduleKey: string }>()
const meta = moduleMeta(props.moduleKey)

const form = reactive({ tableName: '', nullRate: '15%', unit: '' })
const reviewRef = ref('')
const comparison = ref<BaselineComparison | null>(null)
const errorMessage = ref('')
const loading = ref(false)

async function runCheck() {
  errorMessage.value = ''
  comparison.value = null
  loading.value = true
  try {
    comparison.value = await checkNullRate(
      form.tableName.trim(),
      form.nullRate.trim(),
      form.unit || undefined,
    )
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '空值率校验失败'
  } finally {
    loading.value = false
  }
}

async function runReview() {
  errorMessage.value = ''
  comparison.value = null
  loading.value = true
  try {
    comparison.value = await loadIncidentReview(reviewRef.value.trim())
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '事件复核读取失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (props.moduleKey === 'column_profile' && form.tableName) {
    void runCheck()
  }
})

watch(
  () => props.moduleKey,
  () => {
    comparison.value = null
    errorMessage.value = ''
  },
)
</script>

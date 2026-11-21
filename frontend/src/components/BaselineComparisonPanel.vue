<template>
  <section class="baseline-panel" :data-credential="comparison.校验凭证">
    <header class="baseline-head">
      <div>
        <h4>基线比较明细</h4>
        <p class="baseline-sub">
          校验凭证 <strong data-testid="baseline-credential">{{ comparison.校验凭证 }}</strong>
          · 使用基线版本
          <strong data-testid="baseline-version">{{ comparison.使用基线版本 || '—' }}</strong>
          <span v-if="comparison.质量事件编号"> · 关联事件 {{ comparison.质量事件编号 }}</span>
        </p>
      </div>
      <span
        class="baseline-verdict"
        :class="comparison.校验结果 === '异常' ? 'is-bad' : comparison.校验结果 === '正常' ? 'is-ok' : 'is-muted'"
        data-testid="baseline-verdict"
      >
        {{ comparison.校验结果 }}
      </span>
    </header>

    <dl class="baseline-meta">
      <div><dt>目标表</dt><dd>{{ comparison.目标表名 }}</dd></div>
      <div><dt>基线指标</dt><dd>{{ comparison.基线指标 }}</dd></div>
      <div><dt>当前读数</dt><dd data-testid="baseline-reading">{{ comparison.当前读数 }}</dd></div>
      <div v-if="comparison.有效结论">
        <dt>有效结论来源</dt>
        <dd data-testid="baseline-source">{{ comparison.报告来源.有效结论 }}</dd>
      </div>
    </dl>

    <section v-if="comparison.有效结论" class="baseline-block">
      <h5>有效结论</h5>
      <p class="baseline-note" data-testid="baseline-standard">
        判定标准：{{ comparison.有效结论.判定标准 }}
      </p>
      <table class="data-table">
        <thead>
          <tr>
            <th>基线编号</th><th>版本</th><th>来源</th><th>画像批次</th>
            <th>基线下界</th><th>基线上界</th><th>判定单位</th><th>偏离幅度</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>{{ comparison.有效结论.基线编号 }}</td>
            <td>{{ comparison.有效结论.基线版本 }}</td>
            <td>{{ comparison.有效结论.基线来源 }}</td>
            <td>{{ comparison.有效结论.画像批次 || '—' }}</td>
            <td>{{ comparison.有效结论.基线下界 }}</td>
            <td>{{ comparison.有效结论.基线上界 }}</td>
            <td>{{ comparison.有效结论.基线单位 }}</td>
            <td>{{ comparison.有效结论.偏离幅度 }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="baseline-block">
      <h5>基线比较明细</h5>
      <table class="data-table" data-testid="baseline-detail">
        <thead>
          <tr>
            <th>基线编号</th><th>版本</th><th>来源</th><th>画像批次</th>
            <th>基线区间</th><th>当前读数</th><th>判定标准</th><th>偏离幅度</th><th>结论</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in comparison.基线明细" :key="`${row.基线编号}-${row.基线版本}`">
            <td>{{ row.基线编号 }}</td>
            <td>{{ row.基线版本 }}</td>
            <td>{{ row.基线来源 }}</td>
            <td>{{ row.画像批次 || '—' }}</td>
            <td>{{ row.基线下界 }} ~ {{ row.基线上界 }}（{{ row.基线单位 }}）</td>
            <td>{{ row.当前读数 }}</td>
            <td class="baseline-standard">{{ row.判定标准 }}</td>
            <td>{{ row.偏离幅度 }}</td>
            <td>{{ row.是否异常 ? '异常' : '正常' }}</td>
          </tr>
          <tr v-if="!comparison.基线明细.length">
            <td colspan="9" class="empty-state">没有参与比较的有效基线</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="comparison.争议明细.length" class="baseline-block">
      <h5>争议明细</h5>
      <table class="data-table" data-testid="baseline-disputes">
        <thead>
          <tr>
            <th>基线编号</th><th>版本</th><th>来源</th><th>基线区间</th>
            <th>当前读数</th><th>偏离幅度</th><th>结论</th><th>争议原因</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in comparison.争议明细" :key="`${row.基线编号}-${row.基线版本}`">
            <td>{{ row.基线编号 }}</td>
            <td>{{ row.基线版本 }}</td>
            <td>{{ row.基线来源 }}</td>
            <td>{{ row.基线下界 }} ~ {{ row.基线上界 }}（{{ row.基线单位 }}）</td>
            <td>{{ row.当前读数 }}</td>
            <td>{{ row.偏离幅度 }}</td>
            <td>{{ row.结论 }}</td>
            <td class="baseline-standard">{{ row.争议原因 }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="(comparison.无效基线?.length ?? 0) > 0" class="baseline-block">
      <h5>未参与比较的基线</h5>
      <ul class="baseline-invalid" data-testid="baseline-invalid">
        <li v-for="row in comparison.无效基线" :key="`${row.基线编号}-${row.基线版本}`">
          {{ row.基线编号 }}（{{ row.基线版本 }}，{{ row.基线来源 }}）：{{ row.口径问题 }}
        </li>
      </ul>
    </section>

    <p class="baseline-source-note">
      报告来源：有效结论来自 {{ comparison.报告来源.有效结论 }}；
      争议明细来自 {{ comparison.报告来源.争议明细 }}。
    </p>
  </section>
</template>

<script setup lang="ts">
import type { BaselineComparison } from '@/data/baseline'

defineProps<{ comparison: BaselineComparison }>()
</script>

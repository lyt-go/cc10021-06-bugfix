import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type {
  BaselineCheckSummary,
  BaselineComparison,
  IncidentReview,
} from '@/data/baseline'
import type { ActionResult, EntryRow, OverviewResult, PageResult } from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

async function readJson<T>(response: Response, message: string): Promise<T> {
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(detail?.detail ?? message)
  }
  return (await response.json()) as T
}

/** 字段画像入口：用 15% 这类读数回查画像基线，拿回统一单位后的比较明细。 */
export async function checkNullRate(
  tableName: string,
  nullRate: string,
  unit?: string,
): Promise<BaselineComparison> {
  const response = await request('/api/column_profile/null-rate-check', {
    method: 'POST',
    body: JSON.stringify({ table_name: tableName, null_rate: nullRate, unit }),
  })
  return readJson<BaselineComparison>(response, '空值率校验失败')
}

/** 字段画像入口：按校验凭证读取当时该次校验使用的基线。 */
export async function loadProfileCheck(credential: string): Promise<BaselineComparison> {
  const response = await request(`/api/column_profile/checks/${encodeURIComponent(credential)}`)
  return readJson<BaselineComparison>(response, '校验凭证读取失败')
}

/** 事件复核面板：按校验凭证或事件编号读取基线比较明细。 */
export async function loadIncidentReview(reference: string): Promise<IncidentReview> {
  const response = await request(
    `/api/dq_incident/${encodeURIComponent(reference)}/baseline-review`,
  )
  return readJson<IncidentReview>(response, '事件复核读取失败')
}

export async function listBaselineChecks(
  tableName: string,
): Promise<BaselineCheckSummary[]> {
  const query = new URLSearchParams(tableName ? { table_name: tableName } : {}).toString()
  const response = await request(`/api/dq_baseline/checks?${query}`)
  const payload = await readJson<{ items: BaselineCheckSummary[] }>(response, '校验凭证列表读取失败')
  return payload.items
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

/** 基线比较明细的公共类型：字段画像入口和事件复核面板共用同一份校验凭证结构。 */

export type BaselineDetail = {
  基线编号: string
  基线版本: string
  基线指标: string
  基线来源: string
  画像批次: string
  基线上界: string
  基线下界: string
  基线上界数值: number
  基线下界数值: number
  基线单位: string
  当前读数: string
  读数单位: string
  判定单位: string
  判定标准: string
  偏离幅度: string
  是否异常: boolean
  判定说明: string
}

export type DisputeDetail = {
  基线编号: string
  基线版本: string
  基线指标: string
  基线来源: string
  画像批次: string
  基线上界: string
  基线下界: string
  基线单位: string
  当前读数: string
  偏离幅度: string
  结论: string
  与有效结论一致: boolean
  争议原因: string
}

export type EffectiveConclusion = {
  结论: string
  基线编号: string
  基线版本: string
  基线来源: string
  画像批次: string
  基线上界: string
  基线下界: string
  基线单位: string
  偏离幅度: string
  判定标准: string
  结论来源: string
}

export type InvalidBaseline = {
  基线编号: string
  基线版本: string
  基线指标: string
  基线来源: string
  画像批次: string
  口径问题: string
  可用: boolean
}

export type ReportSources = {
  有效结论: string
  争议明细: string
}

export type BaselineComparison = {
  校验凭证: string
  校验时间?: string
  质量事件编号?: string | null
  目标表名: string
  基线指标: string
  当前读数: string
  校验结果: string
  使用基线版本: string
  有效结论: EffectiveConclusion | null
  基线明细: BaselineDetail[]
  争议明细: DisputeDetail[]
  无效基线?: InvalidBaseline[]
  基线快照?: Record<string, string>
  报告来源: ReportSources
}

export type IncidentReview = BaselineComparison & {
  复核对象: string
  事件核对: Record<string, string | number | boolean> | null
}

export type BaselineCheckSummary = {
  校验凭证: string
  校验时间?: string
  目标表名: string
  基线指标: string
  当前读数: string
  校验结果: string
  基线版本: string
  质量事件编号?: string | null
}

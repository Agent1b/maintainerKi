import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

type StatsChartsProps = {
  distributionData: Array<{
    bucket: string
    value: number
  }>
  activityTimeline: Array<{
    date: string
    count: number
  }>
}

export function StatsCharts({ distributionData, activityTimeline }: StatsChartsProps) {
  return (
    <>
      <div className="chart-panel">
        <h3>Score distribution</h3>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={distributionData}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="bucket" />
            <YAxis allowDecimals={false} />
            <Tooltip />
            <Bar dataKey="value" fill="#6d5efc" radius={[8, 8, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="chart-panel">
        <h3>Activity timeline</h3>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={activityTimeline}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="date" />
            <YAxis allowDecimals={false} />
            <Tooltip />
            <Line type="monotone" dataKey="count" stroke="#0ea5e9" strokeWidth={3} dot={{ r: 4 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </>
  )
}

import { useQuery } from '@tanstack/react-query'
import { Activity, Download, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { api, errorMessage, responseData } from '@/api/client'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/hooks/useAuth'
import { formatPrice } from '@/lib/utils'
import type { BackgroundJob } from '@/types/models'

interface AIProviderUsage {
  provider: string
  requests: number
  daily_limit: number | null
  feature_requests: Record<string, number>
}

interface AIUsageSummary {
  date_utc: string
  providers: AIProviderUsage[]
}

export function BackgroundJobsPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const jobsQuery = useQuery({
    queryKey: ['jobs'],
    queryFn: async () => responseData<BackgroundJob[]>(await api.get('/jobs/')),
    refetchInterval: (query) => query.state.data?.some((job) => job.status === 'queued' || job.status === 'running') ? 1500 : false,
  })
  const aiUsageQuery = useQuery({
    queryKey: ['ai-usage'],
    queryFn: async () => responseData<AIUsageSummary>(await api.get('/ai/admin/usage')),
    enabled: isAdmin,
  })
  const jobs = jobsQuery.data ?? []

  async function refreshPage() {
    await Promise.all([
      jobsQuery.refetch(),
      isAdmin ? aiUsageQuery.refetch() : Promise.resolve(),
    ])
  }

  async function downloadInvoice(job: BackgroundJob) {
    if (!job.resource_id) return
    try {
      const response = await api.get(`/jobs/invoices/${job.resource_id}/download`, { responseType: 'blob' })
      const url = URL.createObjectURL(response.data as Blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `invoice-${job.resource_id}.pdf`
      anchor.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  return (
    <main className="account-page jobs-page">
      <div className="account-page-heading">
        <div><p className="eyebrow"><span className="eyebrow-line" /> Work in progress</p><h1>Background jobs</h1></div>
        <Button variant="outline" onClick={() => void refreshPage()}><RefreshCw size={14} /> Refresh</Button>
      </div>
      {isAdmin && (
        <section className="ai-usage-panel" aria-labelledby="ai-usage-title">
          <div className="ai-usage-heading">
            <div>
              <p className="eyebrow"><span className="eyebrow-line" /> Admin only</p>
              <h2 id="ai-usage-title"><Activity size={19} /> AI &amp; Cost Governance</h2>
              <p>Provider request usage for today (UTC). This is request-count tracking, not a dollar-cost estimate.</p>
            </div>
            {aiUsageQuery.data && <span className="ai-usage-date">{aiUsageQuery.data.date_utc} UTC</span>}
          </div>
          {aiUsageQuery.error && (
            <div className="notice notice-error" role="alert">{errorMessage(aiUsageQuery.error)}</div>
          )}
          {aiUsageQuery.isPending ? (
            <p className="route-loading">Loading AI usage...</p>
          ) : aiUsageQuery.data ? (
            <div className="ai-provider-usage-list">
              {aiUsageQuery.data.providers.filter((provider) => provider.provider !== 'mistral').map((provider) => {
                const limit = provider.daily_limit
                const progress = limit ? Math.min(100, (provider.requests / limit) * 100) : 0
                const remaining = limit === null ? null : Math.max(0, limit - provider.requests)
                const activeFeatures = Object.entries(provider.feature_requests)
                  .filter(([, count]) => count > 0)
                return (
                  <article className="ai-provider-usage-card" key={provider.provider}>
                    <div className="ai-provider-usage-heading">
                      <div>
                        <h3>{provider.provider}</h3>
                        <span>Requests today</span>
                      </div>
                      <strong>{provider.requests.toLocaleString()}</strong>
                    </div>
                    <div className="ai-usage-limit">
                      <span>{limit === null ? 'Daily cap' : `${remaining?.toLocaleString()} requests remaining`}</span>
                      <b>{limit === null ? 'No app cap' : `of ${limit.toLocaleString()}`}</b>
                    </div>
                    {limit !== null && (
                      <progress
                        aria-label={`${provider.provider} daily quota`}
                        max="100"
                        value={progress}
                        className={progress >= 90 ? 'near-limit' : undefined}
                      />
                    )}
                    {activeFeatures.length > 0 ? (
                      <ul className="ai-feature-usage">
                        {activeFeatures.map(([feature, count]) => (
                          <li key={feature}><span>{feature.replaceAll('_', ' ')}</span><b>{count.toLocaleString()}</b></li>
                        ))}
                      </ul>
                    ) : <p className="ai-usage-empty">No provider requests recorded today.</p>}
                  </article>
                )
              })}
            </div>
          ) : (
            <p className="ai-usage-empty">AI usage data is not available.</p>
          )}
          <p className="ai-usage-disclaimer">
            App-side limits reset at midnight UTC. Request counts are not dollar costs; your AI provider may enforce separate account limits.
          </p>
        </section>
      )}
      {jobsQuery.error && <div className="notice notice-error" role="alert">{errorMessage(jobsQuery.error)}</div>}
      {jobsQuery.isPending ? <div className="route-loading">Loading your jobs...</div> : jobs.length ? (
        <section className="background-job-list" aria-label="Background job history">
          {jobs.map((job) => {
            const result = job.result ?? {}
            const title = job.task_type === 'invoice'
              ? `Invoice for order #${job.resource_id}`
              : job.task_type === 'ai_product_content'
                ? 'AI product content generation'
                : 'Product CSV import'
            return (
              <article className="background-job-card" key={job.id}>
                <div className="background-job-heading">
                  <div><h2>{title}</h2><p>{new Date(job.created_at).toLocaleString()}</p></div>
                  <span className={`job-status ${job.status}`}>{job.status}</span>
                </div>
                <div className="job-progress-label"><span>{job.status === 'completed' ? 'Complete' : job.status === 'failed' ? 'Stopped' : 'Progress'}</span><b>{Math.max(0, Math.min(100, job.progress))}%</b></div>
                <progress aria-label={`${title} progress`} max="100" value={job.progress} />
                {job.error && <p className="form-message error-text" role="alert">{job.error}</p>}
                {job.task_type === 'product_import' && job.status === 'completed' && (
                  <p className="job-result">Imported {String(result.imported ?? 0)} of {String(result.processed ?? 0)} rows{Number(result.error_count) > 0 ? ` · ${String(result.error_count)} row errors (see details below)` : ''}</p>
                )}
                {job.task_type === 'invoice' && job.status === 'completed' && <Button size="sm" onClick={() => void downloadInvoice(job)}><Download size={14} /> Download PDF invoice</Button>}
                {job.task_type === 'product_import' && Array.isArray(result.errors) && result.errors.length > 0 && (
                  <details className="job-error-details"><summary>Show first {result.errors.length} skipped rows</summary><ul>{result.errors.map((error, index) => <li key={`${job.id}-${index}`}>{String(error)}</li>)}</ul></details>
                )}
                {job.task_type === 'invoice' && job.status === 'completed' && result.total_amount !== undefined && <p className="job-result">Total: {formatPrice(Number(result.total_amount))}</p>}
                {job.task_type === 'ai_product_content' && job.status === 'completed' && (
                  <div className="job-result">
                    {typeof result.description === 'string' && <p>{result.description}</p>}
                    {typeof result.features === 'string' && <pre>{result.features}</pre>}
                  </div>
                )}
              </article>
            )
          })}
        </section>
      ) : <div className="empty-state cart-empty"><h2>No background jobs yet.</h2><p>AI content generation, invoices, and admin CSV imports will appear here with live progress updates.</p></div>}
    </main>
  )
}

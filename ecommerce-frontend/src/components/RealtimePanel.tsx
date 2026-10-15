import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Bell, MessageCircle, Send } from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { api, responseData } from '@/api/client'
import { useWebSocket, type WebSocketStatus } from '@/hooks/use-web-socket'
import { acknowledgeBackgroundJobNotification, pendingBackgroundJobNotifications } from '@/lib/background-jobs'
import { useAuthStore } from '@/stores/auth-store'
import type { BackgroundJob, ChatMessage } from '@/types/models'

interface RealtimeEvent {
  type: string
  data?: Record<string, unknown>
}

interface NotificationItem {
  id: string
  title: string
  message: string
}

function statusLabel(status: WebSocketStatus) {
  if (status === 'connected') return 'Live'
  if (status === 'reconnecting') return 'Reconnecting…'
  if (status === 'connecting') return 'Connecting…'
  return 'Offline'
}

export function RealtimePanel() {
  const user = useAuthStore((state) => state.user)
  const token = useAuthStore((state) => state.token)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [notificationsOpen, setNotificationsOpen] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)
  const [unreadNotifications, setUnreadNotifications] = useState(0)
  const [unreadMessages, setUnreadMessages] = useState(0)
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [liveMessages, setLiveMessages] = useState<ChatMessage[]>([])
  const [activeCustomerId, setActiveCustomerId] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const observedJobStatuses = useRef(new Map<string, string>())
  const jobsQuery = useQuery({
    queryKey: ['jobs'],
    queryFn: async () => responseData<BackgroundJob[]>(await api.get('/jobs/')),
    enabled: Boolean(user),
    refetchInterval: (query) => query.state.data?.some((job) => job.status === 'queued' || job.status === 'running') ? 1500 : false,
  })
  const historyQuery = useQuery({
    queryKey: ['chats', user?.id, user?.role],
    queryFn: async () => responseData<ChatMessage[]>(await api.get('/chats/')),
    enabled: Boolean(user && user.role !== 'admin' && chatOpen),
  })

  const messages = useMemo(() => {
    const unique = new Map<string, ChatMessage>()
    for (const message of [...(historyQuery.data ?? []), ...liveMessages]) {
      const key = message.id === undefined
        ? `${message.sender_id}-${message.created_at}-${message.text}`
        : `id-${message.id}`
      unique.set(key, message)
    }
    return [...unique.values()].slice(-100)
  }, [historyQuery.data, liveMessages])

  const notifyJobCompletion = useCallback((job: BackgroundJob) => {
    const result = job.result ?? {}
    const isImport = job.task_type === 'product_import'
    const title = isImport ? 'CSV import complete' : 'Invoice PDF ready'
    let message = isImport
      ? `Successfully imported ${Number(result.imported ?? 0)} product${Number(result.imported ?? 0) === 1 ? '' : 's'}.`
      : `Invoice PDF for order #${job.resource_id} is ready to download.`
    if (isImport && Number(result.error_count) > 0) {
      message += ` ${Number(result.error_count)} row${Number(result.error_count) === 1 ? '' : 's'} could not be imported.`
    }
    setNotifications((current) => [{ id: job.id, title, message }, ...current].slice(0, 20))
    setUnreadNotifications((count) => count + 1)
    toast.success(title, { description: message, id: `background-job-${job.id}` })
    void queryClient.invalidateQueries({ queryKey: ['admin', 'products'] })
    void queryClient.invalidateQueries({ queryKey: ['products'] })
  }, [queryClient])

  useEffect(() => {
    const pendingNotifications = pendingBackgroundJobNotifications()
    for (const job of jobsQuery.data ?? []) {
      const previousStatus = observedJobStatuses.current.get(job.id)
      const wasTracked = pendingNotifications.has(job.id)
      if ((wasTracked || previousStatus === 'queued' || previousStatus === 'running') && job.status === 'completed') {
        notifyJobCompletion(job)
        acknowledgeBackgroundJobNotification(job.id)
      } else if ((wasTracked || previousStatus === 'queued' || previousStatus === 'running') && job.status === 'failed') {
        const title = job.task_type === 'product_import' ? 'CSV import failed' : 'Invoice generation failed'
        const message = job.error || 'The background task could not be completed.'
        setNotifications((current) => [{ id: job.id, title, message }, ...current].slice(0, 20))
        setUnreadNotifications((count) => count + 1)
        toast.error(title, { description: message, id: `background-job-${job.id}` })
        acknowledgeBackgroundJobNotification(job.id)
      }
      observedJobStatuses.current.set(job.id, job.status)
    }
  }, [jobsQuery.data, notifyJobCompletion])

  const handleMessage = useCallback((event: RealtimeEvent) => {
    const data = event.data ?? {}
    if (event.type === 'notification') {
      const title = typeof data.title === 'string' ? data.title : 'Store update'
      const message = typeof data.message === 'string' ? data.message : 'You have a new update.'
      setNotifications((current) => [{ id: `${Date.now()}-${Math.random()}`, title, message }, ...current].slice(0, 20))
      setUnreadNotifications((count) => count + 1)
      const orderId = typeof data.order_id === 'number' ? data.order_id : null
      toast.message(title, { description: message, id: orderId === null ? undefined : `order-${orderId}` })
      void queryClient.invalidateQueries({ queryKey: ['orders'] })
      void queryClient.invalidateQueries({ queryKey: ['admin', 'orders'] })
    } else if (event.type === 'order.updated') {
      void queryClient.invalidateQueries({ queryKey: ['orders'] })
      void queryClient.invalidateQueries({ queryKey: ['admin', 'orders'] })
    } else if (event.type === 'chat.message' || event.type === 'chat.sent') {
      const chatMessage = data as unknown as ChatMessage
      setLiveMessages((current) => [...current, chatMessage].slice(-100))
      void queryClient.invalidateQueries({ queryKey: ['chats'] })
      if (event.type === 'chat.message') setUnreadMessages((count) => count + 1)
      if (event.type === 'chat.message' && user?.role === 'admin' && chatMessage.sender_id !== user.id) {
        setActiveCustomerId(chatMessage.sender_id)
      }
    } else if (event.type === 'error' && typeof data.message === 'string') {
      toast.error(data.message)
    }
  }, [queryClient, user])

  const { status, send } = useWebSocket<RealtimeEvent>({
    enabled: Boolean(user),
    token,
    onMessage: handleMessage,
  })

  if (!user) return null
  const userId = user.id
  const userRole = user.role
  const customerMessages = messages.filter((message) => message.sender_id !== userId)
  const customerIds = [...new Set(customerMessages.map((message) => message.sender_id))]
  const visibleMessages = messages.filter((message) => userRole !== 'admin'
    ? message.sender_id === userId || message.recipient_id === userId
    : activeCustomerId !== null && (message.sender_id === activeCustomerId || message.recipient_id === activeCustomerId))

  function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const text = draft.trim()
    if (!text) return
    const data = userRole === 'admin'
      ? { text, recipient_id: activeCustomerId }
      : { text }
    if (userRole === 'admin' && !activeCustomerId) {
      toast.error('Select a customer conversation first.')
      return
    }
    if (send({ type: 'chat.send', data })) setDraft('')
    else toast.error('The live connection is not ready. Please try again.')
  }

  return (
    <div className="realtime-panel">
      <div className="realtime-control">
        <button
          type="button"
          className="icon-button realtime-toggle"
          aria-label="Open notifications"
          aria-expanded={notificationsOpen}
          onClick={() => { setNotificationsOpen((value) => !value); setUnreadNotifications(0) }}
        >
          <Bell size={18} />
          {unreadNotifications > 0 && <span className="realtime-unread">{unreadNotifications > 9 ? '9+' : unreadNotifications}</span>}
        </button>
        {notificationsOpen && (
          <section className="realtime-popover" aria-label="Notifications">
            <div className="realtime-heading">
              <div><strong>Notifications</strong><span className={`realtime-status ${status}`}>{statusLabel(status)}</span></div>
              {notifications.length > 0 && <button type="button" onClick={() => setNotifications([])}>Clear</button>}
            </div>
            <div className="realtime-notifications" aria-label="Recent notifications">
              {notifications.length ? notifications.map((item) => (
                <article className="realtime-notification" key={item.id}>
                  <strong>{item.title}</strong><p>{item.message}</p>
                </article>
              )) : <p className="realtime-empty">No new notifications.</p>}
            </div>
          </section>
        )}
      </div>
      <div className="realtime-control">
        <button
          type="button"
          className="icon-button realtime-toggle"
          aria-label={userRole === 'admin' ? 'Open customer chat inbox' : 'Open live support'}
          aria-expanded={chatOpen}
          onClick={() => {
            setUnreadMessages(0)
            if (userRole === 'admin') navigate('/admin/chats')
            else setChatOpen((value) => !value)
          }}
        >
          <MessageCircle size={18} />
          {unreadMessages > 0 && <span className="realtime-unread">{unreadMessages > 9 ? '9+' : unreadMessages}</span>}
        </button>
        {chatOpen && userRole !== 'admin' && (
          <section className="realtime-popover realtime-chat-popover" aria-label={userRole === 'admin' ? 'Customer conversations' : 'Live support'}>
            <div className="realtime-heading">
              <div><strong>{userRole === 'admin' ? 'Customer conversations' : 'Live support'}</strong><span className={`realtime-status ${status}`}>{statusLabel(status)}</span></div>
            </div>
            {userRole === 'admin' && customerIds.length > 0 && (
              <div className="realtime-customer-list">
                {customerIds.map((customerId) => {
                  const customerMessage = customerMessages.find((message) => message.sender_id === customerId)
                  return (
                    <button
                      type="button"
                      className={activeCustomerId === customerId ? 'active' : ''}
                      key={customerId}
                      onClick={() => setActiveCustomerId(customerId)}
                    >
                      Reply to {customerMessage?.sender_name || `Customer #${customerId}`}
                    </button>
                  )
                })}
              </div>
            )}
            <div className="realtime-messages" aria-live="polite">
              {historyQuery.isError && <p className="realtime-empty">Unable to load saved messages.</p>}
              {historyQuery.isPending && <p className="realtime-empty">Loading conversation...</p>}
              {visibleMessages.map((message, index) => (
                <p className={message.sender_id === user.id ? 'mine' : ''} key={`${message.created_at}-${index}`}>
                  <strong>{message.sender_name}: </strong>{message.text}
                </p>
              ))}
            </div>
            <form className="realtime-compose" onSubmit={sendMessage}>
              <input
                aria-label="Support message"
                placeholder={userRole === 'admin' ? 'Reply to customer' : 'Message our team'}
                maxLength={2000}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
              />
              <button type="submit" aria-label="Send message" disabled={!draft.trim()}><Send size={15} /></button>
            </form>
          </section>
        )}
      </div>
    </div>
  )
}

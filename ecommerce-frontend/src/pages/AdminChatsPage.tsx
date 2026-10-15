import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CircleUserRound, MessageCircle, Search, Send, ShieldCheck, Wifi, WifiOff } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { api, errorMessage, responseData } from '@/api/client'
import { useWebSocket, type WebSocketStatus } from '@/hooks/use-web-socket'
import { useAuthStore } from '@/stores/auth-store'
import type { ChatConversation, ChatMessage } from '@/types/models'
import './AdminChatsPage.css'

interface RealtimeEvent {
  type: string
  data?: Record<string, unknown>
}

const conversationsKey = ['chats', 'conversations'] as const
const emptyConversations: ChatConversation[] = []

function connectionLabel(status: WebSocketStatus) {
  if (status === 'connected') return 'Connected'
  if (status === 'reconnecting') return 'Reconnecting'
  if (status === 'connecting') return 'Connecting'
  return 'Offline'
}

function messageTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

function initials(name: string) {
  return name.split(/\s+/).slice(0, 2).map((part) => part.charAt(0)).join('').toUpperCase()
}

export function AdminChatsPage() {
  const user = useAuthStore((state) => state.user)
  const token = useAuthStore((state) => state.token)
  const queryClient = useQueryClient()
  const [selectedCustomerId, setSelectedCustomerId] = useState<number | null>(null)
  const [search, setSearch] = useState('')
  const [draft, setDraft] = useState('')
  const [mobileConversationOpen, setMobileConversationOpen] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const conversationsQuery = useQuery({
    queryKey: conversationsKey,
    queryFn: async () => responseData<ChatConversation[]>(await api.get('/chats/conversations')),
  })
  const conversations = conversationsQuery.data ?? emptyConversations
  const activeCustomerId = selectedCustomerId ?? conversations[0]?.customer_id ?? null
  const activeConversation = conversations.find((item) => item.customer_id === activeCustomerId) ?? null
  const historyQuery = useQuery({
    queryKey: ['chats', 'conversation', activeCustomerId],
    queryFn: async () => responseData<ChatMessage[]>(
      await api.get('/chats/', { params: { customer_id: activeCustomerId } }),
    ),
    enabled: activeCustomerId !== null,
  })

  const filteredConversations = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase()
    if (!needle) return conversations
    return conversations.filter((conversation) =>
      `${conversation.customer_name} ${conversation.customer_email} ${conversation.last_message}`
        .toLocaleLowerCase()
        .includes(needle),
    )
  }, [conversations, search])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'end' })
  }, [historyQuery.data, activeCustomerId])

  const handleMessage = useCallback((event: RealtimeEvent) => {
    const data = event.data ?? {}
    if (event.type === 'error') {
      if (typeof data.message === 'string') toast.error(data.message)
      return
    }
    if ((event.type !== 'chat.message' && event.type !== 'chat.sent') || !user) return
    if (
      typeof data.id !== 'number'
      || typeof data.sender_id !== 'number'
      || typeof data.recipient_id !== 'number'
      || typeof data.text !== 'string'
      || typeof data.created_at !== 'string'
    ) return

    const message = data as unknown as ChatMessage
    const customerId = message.sender_id === user.id ? message.recipient_id : message.sender_id
    queryClient.setQueryData<ChatConversation[]>(conversationsKey, (current) => {
      const items = current ?? []
      const existing = items.find((item) => item.customer_id === customerId)
      const updated: ChatConversation = {
        customer_id: customerId,
        customer_name: existing?.customer_name
          || (message.sender_id === customerId ? message.sender_name : `Customer #${customerId}`),
        customer_email: existing?.customer_email ?? '',
        last_message: message.text,
        last_sender_id: message.sender_id,
        last_message_at: message.created_at,
      }
      return [updated, ...items.filter((item) => item.customer_id !== customerId)]
    })
    queryClient.setQueryData<ChatMessage[]>(['chats', 'conversation', customerId], (current) => {
      const messages = current ?? []
      if (messages.some((item) => item.id === message.id)) return messages
      return [...messages, message].sort((left, right) =>
        new Date(left.created_at).getTime() - new Date(right.created_at).getTime(),
      )
    })
    void queryClient.invalidateQueries({ queryKey: conversationsKey })
  }, [queryClient, user])

  const { status, send } = useWebSocket<RealtimeEvent>({
    enabled: Boolean(user?.role === 'admin'),
    token,
    onMessage: handleMessage,
  })

  function chooseConversation(customerId: number) {
    setSelectedCustomerId(customerId)
    setMobileConversationOpen(true)
  }

  function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const text = draft.trim()
    if (!text || activeCustomerId === null) return
    if (!send({ type: 'chat.send', data: { recipient_id: activeCustomerId, text } })) {
      toast.error('The live connection is not ready. Please try again.')
      return
    }
    setDraft('')
  }

  const messages = historyQuery.data ?? []

  return (
    <main className="admin-chat-page">
      <div className="admin-chat-page-heading">
        <div>
          <p className="eyebrow"><span className="eyebrow-line" /> Customer care</p>
          <h1>Messages</h1>
          <p>One-to-one conversations with your customers.</p>
        </div>
        <Link className="admin-chat-dashboard-link" to="/admin"><ArrowLeft size={15} /> Admin dashboard</Link>
      </div>

      <section className={`admin-chat-shell${mobileConversationOpen ? ' conversation-open' : ''}`} aria-label="Customer chat inbox">
        <aside className="admin-chat-sidebar">
          <div className="admin-chat-sidebar-heading">
            <div><strong>Inbox</strong><span>{conversations.length} conversations</span></div>
            <span className={`admin-chat-connection ${status}`} title={connectionLabel(status)}>
              {status === 'connected' ? <Wifi size={15} /> : <WifiOff size={15} />}
            </span>
          </div>
          <label className="admin-chat-search">
            <Search size={16} />
            <span className="sr-only">Search conversations</span>
            <input
              type="search"
              placeholder="Search or start a conversation"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>

          {conversationsQuery.isPending && <p className="admin-chat-list-state">Loading conversations...</p>}
          {conversationsQuery.isError && (
            <p className="admin-chat-list-state error" role="alert">
              {errorMessage(conversationsQuery.error)}
            </p>
          )}
          {!conversationsQuery.isPending && !conversationsQuery.isError && filteredConversations.length === 0 && (
            <div className="admin-chat-list-empty">
              <MessageCircle size={23} />
              <p>{search ? 'No conversations match your search.' : 'Customer messages will appear here.'}</p>
            </div>
          )}

          <div className="admin-chat-contact-list" aria-label="Conversations">
            {filteredConversations.map((conversation) => (
              <button
                className={`admin-chat-contact${activeCustomerId === conversation.customer_id ? ' active' : ''}`}
                key={conversation.customer_id}
                type="button"
                onClick={() => chooseConversation(conversation.customer_id)}
              >
                <span className="admin-chat-avatar">{initials(conversation.customer_name) || <CircleUserRound size={19} />}</span>
                <span className="admin-chat-contact-copy">
                  <span className="admin-chat-contact-title">
                    <strong>{conversation.customer_name}</strong>
                    <time>{messageTime(conversation.last_message_at)}</time>
                  </span>
                  <span className="admin-chat-contact-preview">{conversation.last_message}</span>
                </span>
              </button>
            ))}
          </div>
        </aside>

        <section className="admin-chat-conversation" aria-label="Selected conversation">
          {activeConversation ? (
            <>
              <header className="admin-chat-conversation-header">
                <button
                  className="admin-chat-back"
                  type="button"
                  aria-label="Back to conversations"
                  onClick={() => setMobileConversationOpen(false)}
                >
                  <ArrowLeft size={19} />
                </button>
                <span className="admin-chat-avatar">{initials(activeConversation.customer_name)}</span>
                <span className="admin-chat-conversation-person">
                  <strong>{activeConversation.customer_name}</strong>
                  <small>{activeConversation.customer_email || 'Customer'}</small>
                </span>
                <span className={`admin-chat-live-status ${status}`}>
                  <i /> {connectionLabel(status)}
                </span>
              </header>

              <div className="admin-chat-messages" aria-live="polite" aria-label="Conversation messages">
                <div className="admin-chat-history-note"><ShieldCheck size={14} /> Messages are saved to this customer’s support history.</div>
                {historyQuery.isPending && <p className="admin-chat-message-state">Loading messages...</p>}
                {historyQuery.isError && (
                  <p className="admin-chat-message-state error" role="alert">
                    {errorMessage(historyQuery.error)}
                  </p>
                )}
                {!historyQuery.isPending && !historyQuery.isError && messages.length === 0 && (
                  <p className="admin-chat-message-state">No messages yet. Say hello to start the conversation.</p>
                )}
                {messages.map((message, index) => {
                  const mine = message.sender_id === user?.id
                  return (
                    <article className={`admin-chat-message-row${mine ? ' mine' : ''}`} key={message.id ?? `${message.created_at}-${index}`}>
                      {!mine && <span className="admin-chat-avatar small">{initials(activeConversation.customer_name)}</span>}
                      <div className="admin-chat-bubble">
                        <p>{message.text}</p>
                        <time>{messageTime(message.created_at)}</time>
                      </div>
                    </article>
                  )
                })}
                <div ref={messagesEndRef} />
              </div>

              <form className="admin-chat-compose" onSubmit={sendMessage}>
                <label className="sr-only" htmlFor="admin-chat-message">Message customer</label>
                <textarea
                  id="admin-chat-message"
                  placeholder="Write a message..."
                  maxLength={2000}
                  rows={1}
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault()
                      event.currentTarget.form?.requestSubmit()
                    }
                  }}
                />
                <button type="submit" aria-label="Send message" disabled={!draft.trim() || status !== 'connected'}>
                  <Send size={17} />
                </button>
              </form>
            </>
          ) : (
            <div className="admin-chat-welcome">
              <span><MessageCircle size={30} /></span>
              <h2>Your customer inbox</h2>
              <p>Select a conversation to read and reply to messages.</p>
            </div>
          )}
        </section>
      </section>
    </main>
  )
}

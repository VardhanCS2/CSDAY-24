import { useEffect, useRef, useState, type Dispatch, type FormEvent, type SetStateAction } from 'react'
import { Bot, LoaderCircle, RotateCcw, Send, Sparkles, Wrench, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Link } from 'react-router-dom'
import { api } from '@/api/client'
import { formatPrice } from '@/lib/utils'
import { ProductImage } from '@/components/ProductImage'
import { useAuthStore } from '@/stores/auth-store'
import './AiChatAssistant.css'

interface ProductSource {
  product_id: number
  name: string
  price: number
  stock: number
  image_url?: string | null
}

interface AssistantMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: ProductSource[]
  sourceLabel?: string
  error?: boolean
}

interface StreamEvent {
  type: 'sources' | 'token' | 'done' | 'error'
  sources?: ProductSource[]
  label?: string
  text?: string
  message?: string
}

interface AgentResponse {
  reply: string
  sources: ProductSource[]
  label: string
}

const welcomeMessage: AssistantMessage = {
  id: 'welcome',
  role: 'assistant',
  content: 'Hi! I can help you find and compare products in our catalogue.',
}

const suggestions = [
  'What products are in stock?',
  'Help me compare products',
]

function streamUrl() {
  return `${(api.defaults.baseURL || '/api').replace(/\/$/, '')}/ai/chat/stream`
}

function updateAssistantMessage(
  setMessages: Dispatch<SetStateAction<AssistantMessage[]>>,
  id: string,
  update: (message: AssistantMessage) => AssistantMessage,
) {
  setMessages((current) => current.map((message) => message.id === id ? update(message) : message))
}

export function AiChatAssistant() {
  const user = useAuthStore((state) => state.user)
  const canUseChatbot = user === null || user.role === 'customer' || user.role === 'admin'
  if (!canUseChatbot) return null
  return <AiChatConversation key={user?.id ?? 'guest'} />
}

function AiChatConversation() {
  const accountId = useAuthStore((state) => state.user?.id ?? null)
  const accountIdRef = useRef<number | null>(accountId)
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [agentMode, setAgentMode] = useState(false)
  const [messages, setMessages] = useState<AssistantMessage[]>([welcomeMessage])
  const messageListRef = useRef<HTMLDivElement>(null)
  const controllerRef = useRef<AbortController | null>(null)
  const messageIdRef = useRef(0)

  useEffect(() => {
    const list = messageListRef.current
    if (list) list.scrollTop = list.scrollHeight
  }, [messages, open])

  useEffect(() => () => controllerRef.current?.abort(), [])

  async function sendMessage(text: string) {
    const question = text.trim()
    if (!question || sending) return

    const conversationHistory = messages
      .filter((message) => message.id !== 'welcome' && message.content && !message.error)
      .slice(-12)
      .map((message) => ({
        role: message.role,
        content: [
          message.content,
          ...(message.sources ?? []).map((source) => `[Product ID: ${source.product_id}]`),
        ].join('\n').slice(0, 3000),
      }))
    const nextId = ++messageIdRef.current
    const assistantId = `assistant-${nextId}`
    const requestAccountId = accountId
    setMessages((current) => [
      ...current,
      { id: `user-${nextId}`, role: 'user', content: question },
      { id: assistantId, role: 'assistant', content: '' },
    ])
    setDraft('')
    setSending(true)

    const controller = new AbortController()
    controllerRef.current = controller
    try {
      if (agentMode) {
        const response = await api.post<AgentResponse>(
          '/ai/agent',
          { message: question },
          { signal: controller.signal },
        )
        if (accountIdRef.current !== requestAccountId) return
        if (!response.data.reply.trim()) throw new Error('The product-search agent returned an empty response.')
        updateAssistantMessage(setMessages, assistantId, (message) => ({
          ...message,
          content: response.data.reply,
          sources: response.data.sources,
          sourceLabel: response.data.label,
        }))
        return
      }
      const accessToken = localStorage.getItem('access_token')
      const response = await fetch(streamUrl(), {
        method: 'POST',
        headers: {
          Accept: 'text/event-stream',
          'Content-Type': 'application/json',
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
        credentials: 'omit',
        signal: controller.signal,
        body: JSON.stringify({ message: question, history: conversationHistory }),
      })
      if (!response.ok) {
        const errorBody: unknown = await response.json().catch(() => null)
        const detail = typeof errorBody === 'object' && errorBody !== null && 'detail' in errorBody
          ? errorBody.detail
          : null
        throw new Error(typeof detail === 'string' ? detail : `Unable to start AI chat (HTTP ${response.status}).`)
      }
      if (!response.body) throw new Error('Your browser could not open the AI response stream.')

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let receivedAnswer = false

      function handleEvent(block: string) {
        if (accountIdRef.current !== requestAccountId) return
        const data = block
          .split(/\r?\n/)
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trim())
          .join('\n')
        if (!data) return

        let event: StreamEvent
        try {
          event = JSON.parse(data) as StreamEvent
        } catch {
          throw new Error('The AI response stream contained invalid data.')
        }
        if (event.type === 'sources' && event.sources) {
          updateAssistantMessage(setMessages, assistantId, (message) => ({
            ...message,
            sources: event.sources,
            sourceLabel: event.label,
          }))
        } else if (event.type === 'token' && event.text) {
          receivedAnswer = true
          updateAssistantMessage(setMessages, assistantId, (message) => ({ ...message, content: message.content + event.text }))
        } else if (event.type === 'error') {
          throw new Error(event.message || 'The AI response could not be completed.')
        }
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let boundary = buffer.match(/\r?\n\r?\n/)
        while (boundary?.index !== undefined) {
          const block = buffer.slice(0, boundary.index)
          buffer = buffer.slice(boundary.index + boundary[0].length)
          handleEvent(block)
          boundary = buffer.match(/\r?\n\r?\n/)
        }
      }
      buffer += decoder.decode()
      if (buffer.trim()) handleEvent(buffer)
      if (!receivedAnswer) throw new Error('The AI assistant returned an empty response. Please try again.')
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return
      if (accountIdRef.current !== requestAccountId) return
      updateAssistantMessage(setMessages, assistantId, (message) => ({
        ...message,
        content: message.content
          ? `${message.content}\n\nResponse interrupted: ${error instanceof Error ? error.message : 'The AI assistant could not respond.'}`
          : (error instanceof Error ? error.message : 'The AI assistant could not respond.'),
        error: true,
      }))
    } finally {
      if (controllerRef.current === controller && accountIdRef.current === requestAccountId) {
        controllerRef.current = null
        setSending(false)
      }
    }
  }

  function submitMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void sendMessage(draft)
  }

  function clearConversation() {
    if (sending) return
    setMessages([welcomeMessage])
  }

  return (
    <div className="ai-assistant">
      {open && (
        <section className="ai-chat-window" role="dialog" aria-label="AI shopping assistant" aria-modal="false">
          <header className="ai-chat-header">
            <span className="ai-chat-avatar" aria-hidden="true"><Bot size={21} /></span>
            <div className="ai-chat-heading">
              <strong>AI shopping assistant</strong>
              <span><Sparkles size={12} /> Catalogue-grounded answers</span>
            </div>
            <button className="ai-chat-icon-button" type="button" aria-label="Start a new AI chat" onClick={clearConversation} disabled={sending}>
              <RotateCcw size={16} />
            </button>
            <button className="ai-chat-icon-button" type="button" aria-label={agentMode ? 'Disable product-search agent' : 'Enable product-search agent'} aria-pressed={agentMode} title="Let the AI call the catalogue search tool" onClick={() => setAgentMode((enabled) => !enabled)} disabled={sending}>
              <Wrench size={16} />
            </button>
            <button className="ai-chat-icon-button" type="button" aria-label="Close AI shopping assistant" onClick={() => setOpen(false)}>
              <X size={19} />
            </button>
          </header>

          <div className="ai-chat-disclaimer">AI assistant · For human help, use Live support in the top bar.</div>

          <div className="ai-chat-messages" ref={messageListRef} aria-live="polite" aria-label="AI conversation">
            {messages.map((message) => (
              <article className={`ai-chat-message ${message.role}${message.error ? ' error' : ''}`} key={message.id}>
                {message.role === 'assistant' && <span className="ai-message-avatar" aria-hidden="true"><Bot size={15} /></span>}
                <div className="ai-message-content">
                  {message.content && (message.role === 'assistant'
                    ? <div className="ai-message-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown></div>
                    : <p>{message.content}</p>)}
                  {message.role === 'assistant' && message.sources && message.sources.length > 0 && (
                    <div className="ai-chat-sources" aria-label="Product sources">
                      <span className="ai-sources-label">{message.sourceLabel || 'Relevant catalogue sources'}</span>
                      {message.sources.map((source) => (
                        <Link className="ai-chat-source" key={source.product_id} to={`/product/${source.product_id}`} onClick={() => setOpen(false)}>
                          <ProductImage
                            className="ai-chat-source-image"
                            product={{ id: source.product_id, name: source.name, image_url: source.image_url ?? null }}
                          />
                          <span><strong>{source.name}</strong><small>Product #{source.product_id} · {source.stock > 0 ? 'In stock' : 'Out of stock'}</small></span>
                          <span className="ai-source-price">{formatPrice(source.price)}</span>
                        </Link>
                      ))}
                    </div>
                  )}
                </div>
              </article>
            ))}
            {sending && <div className="ai-chat-streaming"><LoaderCircle size={14} className="ai-chat-spinner" /> Searching products and writing…</div>}
          </div>

          {messages.length === 1 && (
            <div className="ai-chat-suggestions" aria-label="Suggested questions">
              {suggestions.map((suggestion) => (
                <button key={suggestion} type="button" disabled={sending} onClick={() => void sendMessage(suggestion)}>
                  {suggestion}
                </button>
              ))}
            </div>
          )}

          <form className="ai-chat-compose" onSubmit={submitMessage}>
            <label className="sr-only" htmlFor="ai-chat-input">Ask about products</label>
            <textarea
              id="ai-chat-input"
              placeholder="Ask about products…"
              maxLength={1500}
              rows={1}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  void sendMessage(draft)
                }
              }}
            />
            <button type="submit" aria-label="Send message to AI assistant" disabled={!draft.trim() || sending}>
              {sending ? <LoaderCircle size={17} className="ai-chat-spinner" /> : <Send size={17} />}
            </button>
          </form>
          <div className="ai-chat-footnote">{agentMode ? 'Product-search agent mode · The assistant can call the catalogue search tool.' : 'AI can make mistakes. Check product details before ordering.'}</div>
        </section>
      )}

      <button
        className={`ai-assistant-toggle${open ? ' is-open' : ''}`}
        type="button"
        aria-label={open ? 'Close AI shopping assistant' : 'Open AI shopping assistant'}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="ai-toggle-avatar" aria-hidden="true"><Bot size={25} /></span>
        <span className="ai-toggle-label">{open ? 'Close' : 'Ask AI'}</span>
      </button>
    </div>
  )
}

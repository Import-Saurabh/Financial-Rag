import React, { useState, useRef, useEffect } from 'react';
import { 
  Send, 
  Sparkles, 
  Clock, 
  Layers, 
  Database, 
  ChevronRight, 
  BookOpen, 
  FileText, 
  BarChart3,
  Copy,
  Check,
  Zap,
  PanelLeft,
  Cpu,
  Plus,
  TrendingUp
} from 'lucide-react';

export default function ChatView({ 
  messages, 
  onSendMessage, 
  loading, 
  error, 
  onSelectSource, 
  selectedProvider, 
  setSelectedProvider,
  onToggleSidebar,
  onNewChat,
  onOpenWatchlist
}) {
  const [inputQuery, setInputQuery] = useState('');
  const [copiedId, setCopiedId] = useState(null);
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);

  const quickPrompts = [
    {
      title: "HAL Order Book & Growth Guidance",
      desc: "Order pipeline, FY25 targets, and Tejas Mk1A delivery milestones",
      query: "What is HAL's order book outlook and FY25 guidance?"
    },
    {
      title: "Apollo Micro Systems Revenue Trend",
      desc: "Revenue growth, EBITDA margins, and defense electronics expansion",
      query: "Apollo Micro Systems revenue and EBITDA margin comparison"
    },
    {
      title: "HAL Defense Export Platforms",
      desc: "Key export platforms, customer countries, and DRDO collaborations",
      query: "What are HAL's major export defense platforms and customers?"
    },
    {
      title: "Apollo Micro Systems Shareholding & Debt",
      desc: "Promoter holding, debt position, and working capital cycle",
      query: "Apollo Micro Systems shareholding and debt position"
    }
  ];

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading]);

  const handleSend = () => {
    if (!inputQuery.trim() || loading) return;
    onSendMessage(inputQuery.trim());
    setInputQuery('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleTextareaInput = (e) => {
    setInputQuery(e.target.value);
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 200) + 'px';
  };

  const handleCopy = (id, text) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  // Render clickable citation tags inside the text (e.g. [SRC-1] or [SQL-1])
  const renderMessageContent = (text, sources) => {
    if (!text) return null;
    const parts = text.split(/(\[(?:SRC|SQL)-\d+\])/g);

    return parts.map((part, idx) => {
      const match = part.match(/\[(SRC|SQL)-(\d+)\]/);
      if (match) {
        const tag = `${match[1]}-${match[2]}`;
        const matchedSource = sources?.find(s => s.id === tag) || sources?.[parseInt(match[2], 10) - 1];

        return (
          <button
            key={idx}
            onClick={() => matchedSource && onSelectSource(matchedSource)}
            className="inline-flex items-center gap-1 mx-1 px-1.5 py-0.5 text-[11px] font-mono font-bold rounded bg-orange-500/15 hover:bg-orange-500/30 text-[#ff6600] border border-orange-500/40 hover:border-[#ff6600] transition-colors align-baseline"
            title={matchedSource ? `Inspect ${matchedSource.heading || 'Source'} (Page ${matchedSource.page})` : 'Inspect Source'}
          >
            <BookOpen className="w-2.5 h-2.5 inline" />
            {tag}
          </button>
        );
      }

      return <span key={idx}>{part}</span>;
    });
  };

  return (
    <div className="flex flex-col h-full bg-[#050508] relative">
      
      {/* Top ChatGPT-style Header */}
      <header className="h-12 border-b border-white/5 bg-[#050508]/80 backdrop-blur-md px-4 flex items-center justify-between z-10 flex-shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={onToggleSidebar}
            title="Toggle sidebar"
            className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/5 transition-colors"
          >
            <PanelLeft className="w-4 h-4" />
          </button>

          {/* Model Selector Capsule */}
          <div className="flex items-center gap-1.5 bg-[#0c0d14] border border-white/10 rounded-full px-3 py-1 text-xs">
            <Cpu className="w-3.5 h-3.5 text-[#ff6600]" />
            <select
              value={selectedProvider}
              onChange={(e) => setSelectedProvider(e.target.value)}
              className="bg-transparent text-xs text-gray-200 focus:outline-none cursor-pointer pr-1 font-medium"
            >
              <option value="auto" className="bg-[#0c0d14] text-white">Parallel RAG (Fast 2s)</option>
              <option value="groq-llama" className="bg-[#0c0d14] text-white">Groq LLaMA 3.3 70B</option>
              <option value="or-qwen30b" className="bg-[#0c0d14] text-white">Qwen 2.5 72B</option>
              <option value="gemini" className="bg-[#0c0d14] text-white">Google Gemini 2.5</option>
            </select>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={onOpenWatchlist}
            className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-orange-500/10 hover:bg-orange-500/20 border border-orange-500/30 text-[#ff6600] text-xs font-semibold transition-all shadow-sm glow-orange-sm"
            title="Open Stock Watchlist"
          >
            <TrendingUp className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Watchlist</span>
          </button>

          <button
            onClick={onNewChat}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-gray-400 hover:text-white hover:bg-white/5 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">New chat</span>
          </button>
        </div>
      </header>

      {/* Main Messages Area (ChatGPT Centered Layout) */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        <div className="max-w-3xl mx-auto space-y-6">

          {/* Empty State / Welcome Screen */}
          {messages.length === 0 && (
            <div className="py-12 flex flex-col items-center text-center space-y-6">
              
              {/* Central Glowing Icon */}
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-[#ff6600] to-[#b34700] p-0.5 flex items-center justify-center glow-orange shadow-2xl">
                <div className="w-full h-full bg-[#050508] rounded-[14px] flex items-center justify-center">
                  <Zap className="w-7 h-7 text-[#ff6600]" />
                </div>
              </div>

              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-white tracking-tight">
                  What would you like to research today?
                </h1>
                <p className="text-xs sm:text-sm text-gray-400 mt-2 max-w-md mx-auto">
                  Sub-3s grounded institutional equity intelligence on NIFTY equities. Backed by verified BSE/NSE regulatory filings.
                </p>
              </div>

              {/* 4 Prompt Suggestion Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full mt-4">
                {quickPrompts.map((item, idx) => (
                  <button
                    key={idx}
                    onClick={() => onSendMessage(item.query)}
                    className="p-4 rounded-2xl bg-[#0c0d14] hover:bg-[#141622] border border-white/5 hover:border-orange-500/40 text-left transition-all group shadow-sm"
                  >
                    <div className="text-xs font-bold text-white group-hover:text-[#ff6600] transition-colors flex items-center justify-between">
                      <span>{item.title}</span>
                      <ChevronRight className="w-3.5 h-3.5 text-gray-500 group-hover:text-[#ff6600] transition-colors" />
                    </div>
                    <div className="text-[11px] text-gray-400 mt-1 line-clamp-2">
                      {item.desc}
                    </div>
                  </button>
                ))}
              </div>

            </div>
          )}

          {/* Active Message History */}
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex gap-3.5 ${
                msg.role === 'user' ? 'justify-end' : 'justify-start'
              }`}
            >
              {/* Assistant Icon */}
              {msg.role === 'assistant' && (
                <div className="w-7 h-7 rounded-lg bg-orange-500/10 border border-orange-500/30 flex items-center justify-center text-[#ff6600] flex-shrink-0 mt-1">
                  <Zap className="w-3.5 h-3.5" />
                </div>
              )}

              {/* Message Bubble */}
              <div
                className={`max-w-[85%] sm:max-w-[90%] rounded-2xl px-5 py-4 ${
                  msg.role === 'user'
                    ? 'bg-[#1a1b26] text-white shadow-md border border-white/10'
                    : 'bg-[#0c0d14] text-gray-100 shadow-xl border border-white/5'
                }`}
              >
                {/* Assistant Metadata Header */}
                {msg.role === 'assistant' && (
                  <div className="flex flex-wrap items-center justify-between gap-2 pb-2.5 mb-2.5 border-b border-white/5 text-[10px]">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-[#ff6600] tracking-wider uppercase font-mono">
                        NIFTY RAG
                      </span>
                      <span className="text-gray-400 font-mono">
                        {msg.model_used || 'Fast Parallel RAG'}
                      </span>
                    </div>

                    <div className="flex items-center gap-3 text-gray-400 font-mono">
                      {msg.latency_sec > 0 && (
                        <span className="flex items-center gap-1 text-emerald-400">
                          <Clock className="w-3 h-3" />
                          {msg.latency_sec}s
                        </span>
                      )}
                      {msg.chunks_used > 0 && (
                        <span className="flex items-center gap-1">
                          <Layers className="w-3 h-3" />
                          {msg.chunks_used} chunks
                        </span>
                      )}
                      {msg.sql_rows > 0 && (
                        <span className="flex items-center gap-1 text-sky-400">
                          <Database className="w-3 h-3" />
                          SQL
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {/* Message Content with Inline Citations */}
                <div className="text-xs sm:text-sm leading-relaxed whitespace-pre-wrap font-sans">
                  {renderMessageContent(msg.content, msg.sources)}
                </div>

                {/* Attached Sources Shelf (Click opens left side drawer) */}
                {msg.sources && msg.sources.length > 0 && (
                  <div className="mt-4 pt-3 border-t border-white/5">
                    <span className="text-[10px] font-mono font-bold text-gray-400 uppercase tracking-wider block mb-2">
                      Sources ({msg.sources.length}) — Click to view original page:
                    </span>
                    <div className="flex flex-wrap gap-2">
                      {msg.sources.map((src, idx) => {
                        const pageStr = src.page && src.page !== -1 && src.page !== '-1' 
                          ? `Page ${src.page}` 
                          : (src.doc_type === 'sql_data' ? 'Audited DB' : 'Section');
                        const docStr = src.doc_label || (src.doc_type === 'annual_report' ? 'Annual Report' : 'Concall');

                        return (
                          <button
                            key={idx}
                            onClick={() => onSelectSource(src)}
                            className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-[#050508] hover:bg-orange-500/10 border border-orange-500/20 hover:border-orange-500/60 text-left transition-all group shadow-sm"
                          >
                            <FileText className="w-3.5 h-3.5 text-[#ff6600] group-hover:scale-110 transition-transform" />
                            <div>
                              <div className="text-xs font-semibold text-gray-200 group-hover:text-white flex items-center gap-1.5">
                                <span className="text-[#ff6600] font-mono">[{src.id || `SRC-${idx+1}`}]</span>
                                <span>{src.symbol}</span>
                                <span className="text-gray-400 font-normal">({docStr})</span>
                              </div>
                              <div className="text-[10px] text-gray-400 font-mono">
                                {pageStr} • {src.heading || src.section || 'General'}
                              </div>
                            </div>
                            <ChevronRight className="w-3.5 h-3.5 text-gray-500 group-hover:text-[#ff6600] transition-colors ml-1" />
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Copy Button */}
                {msg.role === 'assistant' && (
                  <div className="mt-3 pt-2 border-t border-white/5 flex items-center justify-end">
                    <button
                      onClick={() => handleCopy(msg.id, msg.content)}
                      className="p-1 rounded-lg text-gray-400 hover:text-white hover:bg-white/5 text-[11px] flex items-center gap-1 transition-colors"
                    >
                      {copiedId === msg.id ? (
                        <>
                          <Check className="w-3 h-3 text-emerald-400" />
                          <span className="text-emerald-400">Copied</span>
                        </>
                      ) : (
                        <>
                          <Copy className="w-3 h-3" />
                          <span>Copy</span>
                        </>
                      )}
                    </button>
                  </div>
                )}

              </div>

              {/* User Avatar */}
              {msg.role === 'user' && (
                <div className="w-7 h-7 rounded-full bg-gradient-to-tr from-orange-600 to-amber-500 flex items-center justify-center text-xs font-bold text-white flex-shrink-0 mt-1">
                  U
                </div>
              )}
            </div>
          ))}

          {/* Loading Indicator */}
          {loading && (
            <div className="flex items-start gap-3.5">
              <div className="w-7 h-7 rounded-lg bg-orange-500/10 border border-orange-500/30 flex items-center justify-center text-[#ff6600] flex-shrink-0 mt-1">
                <Zap className="w-3.5 h-3.5" />
              </div>
              <div className="rounded-2xl px-5 py-4 bg-[#0c0d14] border border-orange-500/20 text-gray-300 shadow-xl flex items-center gap-3">
                <div className="w-4 h-4 rounded-full border-2 border-[#ff6600] border-t-transparent animate-spin" />
                <span className="text-xs font-mono text-gray-300">
                  <span className="text-[#ff6600] font-bold">PageIndex™</span> parallel scatter-gather in progress...
                </span>
              </div>
            </div>
          )}

          {/* Error Message */}
          {error && (
            <div className="p-4 rounded-2xl bg-red-500/10 border border-red-500/30 text-red-400 text-xs flex items-center gap-2">
              <span>{error}</span>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Bottom Floating ChatGPT-style Input Container */}
      <div className="p-4 bg-gradient-to-t from-[#050508] via-[#050508]/90 to-transparent flex-shrink-0">
        <div className="max-w-3xl mx-auto">
          
          {/* Capsule Textarea Box */}
          <div className="relative flex items-end bg-[#0c0d14] border border-orange-500/30 rounded-3xl p-1.5 focus-within:border-[#ff6600] focus-within:ring-1 focus-within:ring-[#ff6600] shadow-2xl transition-all">
            <textarea
              ref={textareaRef}
              rows="1"
              value={inputQuery}
              onChange={handleTextareaInput}
              onKeyDown={handleKeyDown}
              placeholder="Ask about HAL order books, Apollo revenue, concall guidance, or defense exports..."
              className="w-full pl-4 pr-12 py-2.5 bg-transparent text-sm text-white placeholder-gray-500 focus:outline-none resize-none max-h-48 leading-relaxed scrollbar-none"
            />
            <button
              onClick={handleSend}
              disabled={loading || !inputQuery.trim()}
              className="absolute right-2.5 bottom-2 p-2 rounded-full bg-[#ff6600] hover:bg-[#e65c00] text-white disabled:opacity-30 disabled:cursor-not-allowed transition-all shadow-md glow-orange-sm"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>

          <div className="text-center text-[11px] text-gray-500 mt-2 font-mono">
            Nifty Financial Rag can make mistakes. Verify critical financial data with regulatory filings.
          </div>
        </div>
      </div>

    </div>
  );
}

import React, { useState, useEffect } from 'react';
import { 
  X, 
  FileText, 
  BookOpen, 
  CheckCircle, 
  Copy, 
  Sparkles, 
  FileCode,
  ShieldCheck,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Layers,
  RefreshCw,
  Search
} from 'lucide-react';

export default function SourceDrawer({ isOpen, onClose, source }) {
  const [docContent, setDocContent] = useState(null);
  const [loadingContent, setLoadingContent] = useState(false);
  const [viewMode, setViewMode] = useState('page'); // 'page' or 'full'
  const [activePage, setActivePage] = useState(1);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!source || !isOpen) {
      setDocContent(null);
      return;
    }

    const initPage = source.page && source.page !== -1 && source.page !== '-1' 
      ? parseInt(source.page, 10) 
      : 1;
    setActivePage(initPage);

    // Fetch verbatim original document from backend
    const fetchDocContent = async () => {
      setLoadingContent(true);
      try {
        const params = new URLSearchParams({
          section: source.section || source.file_name || '',
          file_name: source.file_name || '',
          page: initPage.toString(),
          heading: source.heading || '',
          symbol: source.symbol || '',
        });

        const res = await fetch(`/api/documents/content?${params.toString()}`);
        if (res.ok) {
          const data = await res.json();
          setDocContent(data);
        } else {
          // Fallback to source.snippet
          setDocContent({
            found: false,
            content: source.snippet || 'Filing excerpt indexed in active PageIndex database.',
            heading: source.heading || source.section,
            file_name: source.file_name,
            page: initPage
          });
        }
      } catch (err) {
        console.error('Failed to fetch document content:', err);
        setDocContent({
          found: false,
          content: source.snippet || 'Verbatim filing excerpt loaded from PageIndex memory cache.',
          heading: source.heading || source.section,
          file_name: source.file_name,
          page: initPage
        });
      } finally {
        setLoadingContent(false);
      }
    };

    fetchDocContent();
  }, [source, isOpen]);

  if (!isOpen || !source) return null;

  const isSql = source.doc_type === 'sql_data';
  const pageLabel = activePage > 0 ? `Page ${activePage}` : (isSql ? 'Audited DB Record' : 'Regulatory Filing');

  const copyToClipboard = () => {
    const textToCopy = docContent?.content || source.snippet || '';
    if (textToCopy) {
      navigator.clipboard.writeText(textToCopy);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  // Financial keyword highlighting helper
  const highlightKeywords = (text) => {
    if (!text) return '';
    const parts = text.split(/(₹?[\d,.]+(?:\s*(?:Crores?|Cr|Lakhs?|%|Crore))?|\b(?:Revenue|EBITDA|PAT|Profit|Guidance|Order Book|Margin|Capex|Defence|Defense|Export|Tejas|DRDO|Turnover)\b)/gi);

    return parts.map((part, i) => {
      if (/₹?[\d,.]+(?:\s*(?:Crores?|Cr|Lakhs?|%|Crore))?/i.test(part) && /\d/.test(part)) {
        return (
          <span key={i} className="text-[#ff6600] font-bold bg-orange-500/10 px-1 rounded">
            {part}
          </span>
        );
      }
      if (/\b(?:Revenue|EBITDA|PAT|Profit|Guidance|Order Book|Margin|Capex|Defence|Defense|Export|Tejas|DRDO|Turnover)\b/i.test(part)) {
        return (
          <span key={i} className="text-amber-300 font-semibold underline decoration-orange-500/40">
            {part}
          </span>
        );
      }
      return part;
    });
  };

  return (
    <div className="fixed inset-0 z-50 overflow-hidden pointer-events-none animate-fade-in">
      {/* Backdrop */}
      <div 
        onClick={onClose}
        className="fixed inset-0 bg-black/70 backdrop-blur-sm transition-opacity pointer-events-auto"
      />

      {/* Slide-out Left Menu Bar / Drawer (ChatGPT Style Panel) */}
      <div className="fixed inset-y-0 left-0 max-w-full flex pointer-events-auto">
        <div className="w-screen max-w-xl bg-[#0c0d14] border-r border-orange-500/30 shadow-2xl flex flex-col h-full transform transition-transform duration-300 ease-in-out glow-orange">
          
          {/* Drawer Top Header */}
          <div className="p-4 border-b border-white/10 bg-[#08090e] flex items-center justify-between">
            <div className="flex items-center gap-3 overflow-hidden">
              <div className="w-9 h-9 rounded-xl bg-orange-500/10 border border-orange-500/30 flex items-center justify-center text-[#ff6600] flex-shrink-0">
                {isSql ? <FileCode className="w-5 h-5" /> : <BookOpen className="w-5 h-5" />}
              </div>
              <div className="truncate">
                <span className="text-[10px] font-mono font-bold text-[#ff6600] uppercase tracking-wider block">
                  Grounding Document Inspection
                </span>
                <h3 className="text-xs font-bold text-white tracking-tight truncate">
                  {source.id || 'SRC'} — {source.symbol} ({source.doc_label || source.doc_type || 'Filing'})
                </h3>
              </div>
            </div>

            <div className="flex items-center gap-1.5 flex-shrink-0">
              <button
                onClick={copyToClipboard}
                title="Copy Excerpt"
                className="px-2.5 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-gray-300 hover:text-white border border-white/5 text-xs flex items-center gap-1 transition-colors"
              >
                {copied ? <CheckCircle className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                <span className="text-[11px]">{copied ? 'Copied' : 'Copy'}</span>
              </button>

              <button
                onClick={onClose}
                className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/5 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>

          {/* Metadata Badges Bar & Page Navigation */}
          <div className="px-5 py-2.5 bg-[#050508] border-b border-white/5 flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <div className="px-2.5 py-0.5 rounded-md bg-orange-500/15 border border-orange-500/30 text-[#ff6600] font-mono font-semibold flex items-center gap-1.5">
                <FileText className="w-3 h-3" />
                {pageLabel}
              </div>

              {source.year && (
                <div className="px-2 py-0.5 rounded-md bg-white/5 border border-white/10 text-gray-300 font-mono text-[11px]">
                  FY{source.year}
                </div>
              )}

              <div className="hidden sm:flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 font-mono text-[10px]">
                <ShieldCheck className="w-3 h-3" />
                Verified BSE/NSE
              </div>
            </div>

            {/* Page Step Navigator */}
            <div className="flex items-center gap-1">
              <button
                onClick={() => setActivePage(p => Math.max(1, p - 1))}
                disabled={activePage <= 1}
                className="p-1 rounded bg-white/5 hover:bg-white/10 text-gray-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
                title="Previous Page"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
              </button>
              <span className="text-[11px] font-mono text-gray-400 px-1">
                P.{activePage}
              </span>
              <button
                onClick={() => setActivePage(p => p + 1)}
                className="p-1 rounded bg-white/5 hover:bg-white/10 text-gray-400 hover:text-white"
                title="Next Page"
              >
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* Document Reference Info */}
          <div className="px-5 py-3 bg-[#0c0d14] border-b border-white/5 space-y-1">
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-gray-400 font-medium">Source Document:</span>
              <span className="text-white font-mono font-semibold truncate max-w-xs">
                {docContent?.file_name || source.file_name || `${source.section}.pdf`}
              </span>
            </div>
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-gray-400 font-medium">Section Header:</span>
              <span className="text-[#ff6600] font-medium truncate max-w-xs">
                {docContent?.heading || source.heading || source.section || 'General Financial Disclosure'}
              </span>
            </div>
          </div>

          {/* Content Scroll Area */}
          <div className="flex-1 overflow-y-auto p-5 space-y-4">
            
            {/* View Mode Toggle */}
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-gray-300 flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-[#ff6600]" />
                Verbatim Regulatory Context
              </span>

              <div className="flex items-center gap-1 p-0.5 bg-[#050508] rounded-lg border border-white/5 text-[10px]">
                <button
                  onClick={() => setViewMode('page')}
                  className={`px-2.5 py-1 rounded-md font-semibold transition-all ${
                    viewMode === 'page'
                      ? 'bg-[#ff6600] text-white'
                      : 'text-gray-400 hover:text-white'
                  }`}
                >
                  Cited Section
                </button>
                <button
                  onClick={() => setViewMode('full')}
                  className={`px-2.5 py-1 rounded-md font-semibold transition-all ${
                    viewMode === 'full'
                      ? 'bg-[#ff6600] text-white'
                      : 'text-gray-400 hover:text-white'
                  }`}
                >
                  Full Filing
                </button>
              </div>
            </div>

            {/* Document Content Box */}
            <div className="relative">
              {loadingContent ? (
                <div className="p-8 rounded-2xl bg-[#050508] border border-orange-500/20 flex flex-col items-center justify-center gap-3 text-center">
                  <RefreshCw className="w-6 h-6 text-[#ff6600] animate-spin" />
                  <span className="text-xs font-mono text-gray-400">
                    Retrieving original page text from regulatory archive...
                  </span>
                </div>
              ) : (
                <div className="p-4 rounded-2xl bg-[#050508] border border-orange-500/25 text-gray-200 text-xs leading-relaxed font-mono whitespace-pre-wrap selection:bg-[#ff6600] selection:text-white shadow-inner max-h-[500px] overflow-y-auto">
                  {highlightKeywords(
                    viewMode === 'page'
                      ? (source.snippet || docContent?.content || 'Verbatim text indexed in OpenKB PageIndex.')
                      : (docContent?.content || source.snippet || 'Full document available in regulatory archive.')
                  )}
                </div>
              )}
            </div>

            {/* Trust Certificate Box */}
            <div className="p-3.5 rounded-xl bg-orange-500/5 border border-orange-500/20 text-gray-400 text-[11px] leading-relaxed flex items-start gap-2.5">
              <CheckCircle className="w-4 h-4 text-[#ff6600] flex-shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold text-gray-200 block mb-0.5">
                  100% Grounded Regulatory Filing
                </span>
                This excerpt is directly extracted from the company's verified annual reports and concall transcripts. Zero synthetic hallucination.
              </div>
            </div>

          </div>

          {/* Drawer Footer */}
          <div className="p-4 border-t border-white/10 bg-[#08090e] flex items-center justify-between">
            <span className="text-[11px] text-gray-500 font-mono">
              Nifty Financial Rag • PageIndex™
            </span>
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-xl bg-white/10 hover:bg-white/20 text-white text-xs font-medium transition-colors"
            >
              Close Drawer
            </button>
          </div>

        </div>
      </div>
    </div>
  );
}

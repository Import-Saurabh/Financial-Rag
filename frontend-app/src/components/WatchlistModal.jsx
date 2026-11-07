import React, { useState, useEffect } from 'react';
import { 
  X, 
  Plus, 
  Trash2, 
  TrendingUp, 
  Calendar, 
  Clock, 
  CheckCircle, 
  AlertCircle, 
  FileText, 
  PhoneCall, 
  Sparkles,
  ExternalLink,
  ShieldCheck,
  Search
} from 'lucide-react';

export default function WatchlistModal({ 
  isOpen, 
  onClose, 
  currentUser, 
  onQueryStock,
  onOpenAuth 
}) {
  const [watchlist, setWatchlist] = useState([]);
  const [newSymbol, setNewSymbol] = useState('');
  const [loading, setLoading] = useState(false);
  const [actionMsg, setActionMsg] = useState(null);

  const fetchWatchlist = async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem('nifty_auth_token');
      const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
      const res = await fetch('/api/user/watchlist', { headers });
      if (res.ok) {
        const data = await res.json();
        setWatchlist(data.watchlist || []);
      }
    } catch (err) {
      console.error('Failed to load watchlist:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchWatchlist();
      setActionMsg(null);
    }
  }, [isOpen, currentUser]);

  const handleAddStock = async (e) => {
    e.preventDefault();
    const sym = newSymbol.trim().toUpperCase();
    if (!sym) return;

    try {
      const token = localStorage.getItem('nifty_auth_token');
      const headers = {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {})
      };
      const res = await fetch('/api/user/watchlist', {
        method: 'POST',
        headers,
        body: JSON.stringify({ symbol: sym })
      });
      if (res.ok) {
        const data = await res.json();
        setWatchlist(data.watchlist || []);
        setNewSymbol('');
        setActionMsg({ type: 'success', text: `Added ${sym} to your watchlist.` });
      }
    } catch (err) {
      setActionMsg({ type: 'error', text: err.message });
    }
  };

  const handleRemoveStock = async (sym) => {
    try {
      const token = localStorage.getItem('nifty_auth_token');
      const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
      const res = await fetch(`/api/user/watchlist/${sym}`, {
        method: 'DELETE',
        headers
      });
      if (res.ok) {
        const data = await res.json();
        setWatchlist(data.watchlist || []);
        setActionMsg({ type: 'success', text: `Untracked ${sym}.` });
      }
    } catch (err) {
      setActionMsg({ type: 'error', text: err.message });
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fade-in">
      <div 
        onClick={(e) => e.stopPropagation()}
        className="relative w-full max-w-3xl max-h-[85vh] flex flex-col bg-[#08090e] border border-orange-500/25 rounded-2xl shadow-2xl glow-orange overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-white/10 bg-[#0c0d14]/80">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-orange-500/10 border border-orange-500/30 flex items-center justify-center glow-orange-sm">
              <TrendingUp className="w-5 h-5 text-[#ff6600]" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold text-white tracking-tight">
                  Corporate Concall & Filing Watchlist
                </h2>
                <span className="px-2 py-0.5 rounded bg-orange-500/15 border border-orange-500/30 text-[#ff6600] font-mono text-[10px] font-bold">
                  {currentUser?.username || 'Guest'}
                </span>
              </div>
              <p className="text-xs text-gray-400 mt-0.5">
                Track upcoming earnings calls, board meetings, and BSE/NSE annual report filings.
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-2 text-gray-400 hover:text-white rounded-lg hover:bg-white/5 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Action / Add Bar */}
        <div className="p-4 border-b border-white/5 bg-[#050508]/50">
          <form onSubmit={handleAddStock} className="flex gap-2">
            <div className="relative flex-1">
              <input
                type="text"
                value={newSymbol}
                onChange={(e) => setNewSymbol(e.target.value)}
                placeholder="Track stock symbol (e.g., HAL, APOLLO, MTAR, RELIANCE, TCS)..."
                className="w-full pl-9 pr-3 py-2 bg-[#0c0d14] border border-white/10 rounded-xl text-xs text-white placeholder-gray-500 focus:outline-none focus:border-orange-500/50 uppercase font-mono"
              />
              <Search className="w-4 h-4 text-gray-500 absolute left-3 top-2.5" />
            </div>
            <button
              type="submit"
              disabled={!newSymbol.trim()}
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-[#ff6600] hover:bg-[#e65c00] text-white text-xs font-semibold transition-all shadow-md glow-orange-sm disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Plus className="w-4 h-4" />
              Track Stock
            </button>
          </form>

          {actionMsg && (
            <div className={`mt-2 text-xs font-mono px-3 py-1.5 rounded-lg border ${
              actionMsg.type === 'success' 
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' 
                : 'bg-red-500/10 border-red-500/30 text-red-400'
            }`}>
              {actionMsg.text}
            </div>
          )}
        </div>

        {/* Watchlist Items */}
        <div className="flex-1 overflow-y-auto p-5 space-y-3">
          {watchlist.length === 0 ? (
            <div className="text-center py-12 text-gray-500 text-xs">
              <TrendingUp className="w-8 h-8 mx-auto text-gray-600 mb-2 opacity-50" />
              No stocks in your watchlist yet. Add symbols like <code className="text-[#ff6600]">HAL</code> or <code className="text-[#ff6600]">APOLLO</code> above.
            </div>
          ) : (
            watchlist.map((item) => (
              <div
                key={item.symbol}
                className="p-4 rounded-xl bg-[#0c0d14] border border-white/5 hover:border-orange-500/30 transition-all space-y-3"
              >
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold text-sm text-[#ff6600] bg-orange-500/10 px-2 py-0.5 rounded border border-orange-500/20">
                        {item.symbol}
                      </span>
                      <span className="font-semibold text-xs text-white">
                        {item.company_name}
                      </span>
                      <span className="text-[10px] text-gray-400 font-mono">
                        ({item.fiscal_period})
                      </span>
                    </div>

                    <div className="text-xs text-gray-300 mt-1">
                      {item.event_type}
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => {
                        onQueryStock(item.symbol, `What is the latest concall guidance and financial outlook for ${item.symbol}?`);
                        onClose();
                      }}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-orange-500/15 hover:bg-orange-500/25 border border-orange-500/30 text-[#ff6600] text-xs font-semibold transition-all shadow-sm"
                      title="Analyze with RAG"
                    >
                      <Sparkles className="w-3.5 h-3.5" />
                      Ask RAG
                    </button>

                    <button
                      onClick={() => handleRemoveStock(item.symbol)}
                      className="p-1.5 rounded-lg text-gray-500 hover:text-red-400 hover:bg-white/5 transition-colors"
                      title="Remove from watchlist"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* Details & Status Grid */}
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2.5 pt-2 border-t border-white/5 text-[11px]">
                  <div className="flex items-center gap-2 text-gray-300">
                    <Calendar className="w-3.5 h-3.5 text-[#ff6600]" />
                    <span>Concall: <strong>{item.scheduled_date} {item.scheduled_time}</strong></span>
                  </div>

                  <div className="flex items-center gap-2">
                    <Clock className="w-3.5 h-3.5 text-gray-400" />
                    <span className="text-gray-400">Meeting:</span>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                      item.meeting_status === 'Scheduled'
                        ? 'bg-amber-500/15 text-amber-300 border border-amber-500/30'
                        : item.meeting_status === 'Conducted'
                        ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                        : 'bg-gray-800 text-gray-400'
                    }`}>
                      {item.meeting_status}
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    <FileText className="w-3.5 h-3.5 text-gray-400" />
                    <span className="text-gray-400">Report:</span>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                      item.published_status?.includes('Published')
                        ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                        : 'bg-blue-500/15 text-blue-300 border border-blue-500/30'
                    }`}>
                      {item.published_status}
                    </span>
                  </div>
                </div>

                {item.notes && (
                  <div className="text-[11px] text-gray-400 bg-[#050508] p-2.5 rounded-lg border border-white/5">
                    <span className="text-[#ff6600] font-semibold">Notes:</span> {item.notes}
                  </div>
                )}
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-white/10 bg-[#0c0d14]/80 flex items-center justify-between text-xs text-gray-400">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
            <span>Synced with official BSE/NSE corporate disclosures</span>
          </div>
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 text-gray-300 font-semibold transition-colors"
          >
            Close
          </button>
        </div>

      </div>
    </div>
  );
}

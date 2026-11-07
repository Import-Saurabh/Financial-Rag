import React, { useState, useEffect } from 'react';
import { 
  UploadCloud, 
  FileText, 
  RefreshCw, 
  CheckCircle, 
  AlertTriangle, 
  Users, 
  Coins, 
  ShieldCheck, 
  Database, 
  Activity,
  Smartphone,
  Edit2,
  Trash2,
  Play,
  Calendar,
  Bell,
  Clock,
  Radio,
  ExternalLink,
  CheckSquare,
  Search
} from 'lucide-react';

export default function AdminDashboard({ currentUser }) {
  // Navigation within admin dashboard
  const [adminSection, setAdminSection] = useState('catalog'); // 'catalog', 'credits', 'watchlists'

  // Documents state
  const [allDocs, setAllDocs] = useState([]);
  const [ingestedDocs, setIngestedDocs] = useState([]);
  const [pendingDocs, setPendingDocs] = useState([]);
  const [docFilterTab, setDocFilterTab] = useState('all'); // 'all', 'pending', 'ingested'
  const [docSearch, setDocSearch] = useState('');
  const [selectedPendingDoc, setSelectedPendingDoc] = useState(null);
  const [ingestingPending, setIngestingPending] = useState(false);
  const [pendingIngestMsg, setPendingIngestMsg] = useState(null);

  // WhatsApp users & credits
  const [waUsers, setWaUsers] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [uploadMsg, setUploadMsg] = useState(null);
  const [reindexMsg, setReindexMsg] = useState(null);

  // Watchlists & Corporate Calendar
  const [watchlists, setWatchlists] = useState([]);
  const [webWatchlists, setWebWatchlists] = useState({});
  const [calendarEvents, setCalendarEvents] = useState([]);
  const [broadcasting, setBroadcasting] = useState(false);
  const [broadcastMsg, setBroadcastMsg] = useState(null);

  // Upload Form state
  const [selectedFile, setSelectedFile] = useState(null);
  const [symbol, setSymbol] = useState('HAL');
  const [docType, setDocType] = useState('annual_report');

  // WhatsApp limit edit state
  const [editingPhone, setEditingPhone] = useState(null);
  const [editLimitVal, setEditLimitVal] = useState(10000);
  const [editWhitelistVal, setEditWhitelistVal] = useState(false);

  const fetchAllData = async () => {
    setLoading(true);
    try {
      // 1. Fetch documents (all, ingested & pending)
      const docRes = await fetch('/api/admin/documents');
      if (docRes.ok) {
        const dData = await docRes.json();
        setAllDocs(dData.all_documents || []);
        setIngestedDocs(dData.ingested || []);
        setPendingDocs(dData.pending || []);
        if (dData.pending && dData.pending.length > 0 && !selectedPendingDoc) {
          setSelectedPendingDoc(dData.pending[0]);
        }
      }

      // 2. Fetch WhatsApp users
      const waRes = await fetch('/api/admin/whatsapp/users');
      if (waRes.ok) {
        const wData = await waRes.json();
        setWaUsers(wData.users || []);
      }

      // 3. Fetch admin stats
      const sRes = await fetch('/api/admin/stats');
      if (sRes.ok) {
        const sData = await sRes.json();
        setStats(sData);
      }

      // 4. Fetch watchlists & calendar
      const wlRes = await fetch('/api/admin/whatsapp/watchlists');
      if (wlRes.ok) {
        const wlData = await wlRes.json();
        setWatchlists(wlData.watchlists || []);
        setWebWatchlists(wlData.web_watchlists || {});
        setCalendarEvents(wlData.calendar || []);
      }
    } catch (err) {
      console.error('Failed to load admin data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAllData();
  }, []);

  // Ingest a selected pending item
  const handleIngestPending = async () => {
    if (!selectedPendingDoc) return;
    setIngestingPending(true);
    setPendingIngestMsg(null);

    try {
      const res = await fetch('/api/admin/documents/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filename: selectedPendingDoc.file_name,
          symbol: selectedPendingDoc.symbol || 'HAL',
          doc_type: selectedPendingDoc.doc_type === 'Concall Transcript' ? 'concall' : 'annual_report',
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Ingestion failed');
      }

      setPendingIngestMsg({
        type: 'success',
        text: `System OK: Ingestion started and completed for ${selectedPendingDoc.file_name}! Added to OpenKB PageIndex.`
      });

      setSelectedPendingDoc(null);
      // Refresh list
      await fetchAllData();
      setDocFilterTab('ingested');
    } catch (err) {
      setPendingIngestMsg({ type: 'error', text: err.message });
    } finally {
      setIngestingPending(false);
    }
  };

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!selectedFile) return;

    setUploading(true);
    setUploadMsg(null);

    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('symbol', symbol);
    formData.append('doc_type', docType);

    try {
      const res = await fetch('/api/admin/upload', {
        method: 'POST',
        body: formData,
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Upload failed');
      }

      setUploadMsg({
        type: 'success',
        text: `Successfully ingested ${selectedFile.name} for ${symbol}. Index updated!`
      });
      setSelectedFile(null);
      const fileInput = document.getElementById('file-upload-input');
      if (fileInput) fileInput.value = '';

      fetchAllData();
    } catch (err) {
      setUploadMsg({ type: 'error', text: err.message });
    } finally {
      setUploading(false);
    }
  };

  const handleReindex = async () => {
    setReindexing(true);
    setReindexMsg(null);
    try {
      const res = await fetch('/api/admin/reindex', { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Reindex failed');
      setReindexMsg({ type: 'success', text: data.message });
      fetchAllData();
    } catch (err) {
      setReindexMsg({ type: 'error', text: err.message });
    } finally {
      setReindexing(false);
    }
  };

  const handleSaveWaLimit = async (phone) => {
    try {
      const res = await fetch('/api/admin/whatsapp/limit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          phone: phone,
          limit: parseInt(editLimitVal, 10),
          whitelist: editWhitelistVal,
        }),
      });

      if (res.ok) {
        setEditingPhone(null);
        fetchAllData();
      }
    } catch (err) {
      alert('Failed to update limit: ' + err.message);
    }
  };

  const handleBroadcastAlert = async (event) => {
    setBroadcasting(true);
    setBroadcastMsg(null);
    try {
      const res = await fetch('/api/admin/whatsapp/broadcast-alert', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: event.symbol,
          title: `${event.symbol} ${event.fiscal_period} ${event.event_type}`,
          details: `• Date: ${event.scheduled_date} ${event.scheduled_time}\n• Status: ${event.meeting_status} (${event.published_status})\n• Details: ${event.notes || 'Management review'}`,
        }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Broadcast failed');
      setBroadcastMsg({
        type: 'success',
        text: `Alert sent to ${data.notified_count} WhatsApp users tracking ${event.symbol}!`
      });
    } catch (err) {
      setBroadcastMsg({ type: 'error', text: err.message });
    } finally {
      setBroadcasting(false);
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
      
      {/* Dashboard Top Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-orange-500/20">
        <div>
          <div className="flex items-center gap-2">
            <span className="px-2.5 py-0.5 rounded bg-orange-500/15 border border-orange-500/30 text-[#ff6600] font-mono text-xs font-bold uppercase">
              Admin Workspace
            </span>
            <span className="text-xs text-gray-400 font-mono">
              Role: {currentUser?.role || 'admin'}
            </span>
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight mt-1">
            Institutional Ingestion & Credit Telemetry
          </h1>
          <p className="text-xs text-gray-400 mt-0.5">
            Ingest fresh company filings, manage token limits for WhatsApp users, and track corporate concall watchlists.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={fetchAllData}
            disabled={loading}
            className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-[#0c0d14] hover:bg-white/5 border border-white/10 text-gray-300 text-xs font-semibold transition-all shadow-sm"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh Data
          </button>

          <button
            onClick={handleReindex}
            disabled={reindexing}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-orange-500/15 hover:bg-orange-500/25 border border-orange-500/40 text-[#ff6600] text-xs font-semibold transition-all shadow-md glow-orange-sm disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${reindexing ? 'animate-spin text-[#ff6600]' : ''}`} />
            {reindexing ? 'Reindexing Vectors...' : 'Trigger Reindex'}
          </button>
        </div>
      </div>

      {/* Admin Section Tabs */}
      <div className="flex items-center gap-2 border-b border-white/10 pb-2">
        <button
          onClick={() => setAdminSection('catalog')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-all ${
            adminSection === 'catalog'
              ? 'bg-[#ff6600] text-white shadow-md glow-orange-sm'
              : 'text-gray-400 hover:text-white hover:bg-white/5'
          }`}
        >
          <Database className="w-3.5 h-3.5" />
          Ingested vs Pending Documents
          {pendingDocs.length > 0 && (
            <span className="px-1.5 py-0.2 rounded-full bg-black/40 text-orange-200 text-[10px] font-bold">
              {pendingDocs.length} Pending
            </span>
          )}
        </button>

        <button
          onClick={() => setAdminSection('watchlists')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-all ${
            adminSection === 'watchlists'
              ? 'bg-[#ff6600] text-white shadow-md glow-orange-sm'
              : 'text-gray-400 hover:text-white hover:bg-white/5'
          }`}
        >
          <Bell className="w-3.5 h-3.5" />
          WhatsApp Watchlists & Concalls
          <span className="px-1.5 py-0.2 rounded-full bg-black/40 text-orange-200 text-[10px] font-bold">
            {watchlists.length} Users
          </span>
        </button>

        <button
          onClick={() => setAdminSection('credits')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-all ${
            adminSection === 'credits'
              ? 'bg-[#ff6600] text-white shadow-md glow-orange-sm'
              : 'text-gray-400 hover:text-white hover:bg-white/5'
          }`}
        >
          <Coins className="w-3.5 h-3.5" />
          WhatsApp Token Quotas
        </button>
      </div>

      {/* Notifications */}
      {reindexMsg && (
        <div className={`p-4 rounded-xl border text-xs flex items-center gap-2 ${
          reindexMsg.type === 'success' 
            ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' 
            : 'bg-red-500/10 border-red-500/30 text-red-400'
        }`}>
          <CheckCircle className="w-4 h-4 flex-shrink-0" />
          <span>{reindexMsg.text}</span>
        </div>
      )}

      {/* Stats Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-5 rounded-2xl bg-[#0c0d14] border border-white/5 shadow-lg flex items-center justify-between">
          <div>
            <span className="text-[11px] font-mono uppercase text-gray-400 block font-semibold">
              Live Ingested Docs
            </span>
            <span className="text-2xl font-bold text-white font-mono mt-1 block">
              {ingestedDocs.length}
            </span>
          </div>
          <div className="w-10 h-10 rounded-xl bg-orange-500/10 border border-orange-500/30 flex items-center justify-center text-[#ff6600]">
            <Database className="w-5 h-5" />
          </div>
        </div>

        <div className="p-5 rounded-2xl bg-[#0c0d14] border border-white/5 shadow-lg flex items-center justify-between">
          <div>
            <span className="text-[11px] font-mono uppercase text-gray-400 block font-semibold">
              Pending Ingestion
            </span>
            <span className="text-2xl font-bold text-amber-400 font-mono mt-1 block">
              {pendingDocs.length} Files
            </span>
          </div>
          <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400">
            <Clock className="w-5 h-5" />
          </div>
        </div>

        <div className="p-5 rounded-2xl bg-[#0c0d14] border border-white/5 shadow-lg flex items-center justify-between">
          <div>
            <span className="text-[11px] font-mono uppercase text-gray-400 block font-semibold">
              Tracked Watchlists
            </span>
            <span className="text-2xl font-bold text-sky-400 font-mono mt-1 block">
              {watchlists.length} Users
            </span>
          </div>
          <div className="w-10 h-10 rounded-xl bg-sky-500/10 border border-sky-500/30 flex items-center justify-center text-sky-400">
            <Bell className="w-5 h-5" />
          </div>
        </div>

        <div className="p-5 rounded-2xl bg-[#0c0d14] border border-white/5 shadow-lg flex items-center justify-between">
          <div>
            <span className="text-[11px] font-mono uppercase text-gray-400 block font-semibold">
              LLM Providers Live
            </span>
            <span className="text-2xl font-bold text-emerald-400 font-mono mt-1 block">
              {stats?.healthy_providers || 4} Active
            </span>
          </div>
          <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
            <Activity className="w-5 h-5" />
          </div>
        </div>
      </div>

      {/* SECTION 1: INGESTED VS PENDING DOCUMENTS */}
      {adminSection === 'catalog' && (
        <div className="space-y-6">
          
          {/* Ingestion Status Action Banner */}
          <div className="p-5 rounded-2xl bg-gradient-to-r from-[#0c0d14] to-[#151722] border border-orange-500/30 shadow-xl flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono font-bold text-[#ff6600] uppercase tracking-wider">
                  Knowledge Ingestion Engine
                </span>
                <span className="text-xs px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono">
                  System OK
                </span>
              </div>
              <h2 className="text-lg font-bold text-white tracking-tight">
                {selectedPendingDoc 
                  ? `Selected for Ingestion: ${selectedPendingDoc.name}`
                  : 'Select an available document to ingest into OpenKB PageIndex'}
              </h2>
              <p className="text-xs text-gray-400">
                Extract page text, generate semantic vectors, and immediately enable sub-3s RAG answering.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={handleIngestPending}
                disabled={!selectedPendingDoc || ingestingPending}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[#ff6600] hover:bg-[#e65c00] text-white font-semibold text-xs transition-all shadow-lg glow-orange-sm disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {ingestingPending ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    Ingesting into PageIndex...
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4 fill-white" />
                    Ingest Selected Document
                  </>
                )}
              </button>
            </div>
          </div>

          {pendingIngestMsg && (
            <div className={`p-4 rounded-xl border text-xs flex items-center gap-2 ${
              pendingIngestMsg.type === 'success' 
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' 
                : 'bg-red-500/10 border-red-500/30 text-red-400'
            }`}>
              <CheckCircle className="w-4 h-4 flex-shrink-0" />
              <span>{pendingIngestMsg.text}</span>
            </div>
          )}

          {/* Sub-tabs: All vs Pending vs Ingested + Search Filter */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-white/5 pb-3">
            <div className="flex items-center gap-2 overflow-x-auto">
              <button
                onClick={() => setDocFilterTab('all')}
                className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                  docFilterTab === 'all'
                    ? 'bg-[#ff6600]/20 border border-[#ff6600]/50 text-[#ff6600] shadow-sm glow-orange-sm'
                    : 'text-gray-400 hover:text-white hover:bg-white/5'
                }`}
              >
                <FileText className="w-3.5 h-3.5" />
                All Available API Docs ({allDocs.length})
              </button>

              <button
                onClick={() => setDocFilterTab('pending')}
                className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                  docFilterTab === 'pending'
                    ? 'bg-amber-500/15 border border-amber-500/40 text-amber-300 shadow-sm'
                    : 'text-gray-400 hover:text-white hover:bg-white/5'
                }`}
              >
                <Clock className="w-3.5 h-3.5" />
                Pending Ingestion ({pendingDocs.length})
              </button>

              <button
                onClick={() => setDocFilterTab('ingested')}
                className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                  docFilterTab === 'ingested'
                    ? 'bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 shadow-sm'
                    : 'text-gray-400 hover:text-white hover:bg-white/5'
                }`}
              >
                <CheckCircle className="w-3.5 h-3.5" />
                Live Ingested Items ({ingestedDocs.length})
              </button>
            </div>

            {/* Quick Search */}
            <div className="relative w-full sm:w-64">
              <input
                type="text"
                value={docSearch}
                onChange={(e) => setDocSearch(e.target.value)}
                placeholder="Search documents by name or symbol..."
                className="w-full pl-8 pr-3 py-1.5 bg-[#050508] border border-white/10 rounded-lg text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-[#ff6600]/50"
              />
              <Search className="w-3.5 h-3.5 text-gray-500 absolute left-2.5 top-2" />
            </div>
          </div>

          {/* TAB 1: ALL AVAILABLE API DOCUMENTS */}
          {docFilterTab === 'all' && (
            <div className="p-6 rounded-2xl bg-[#0c0d14] border border-orange-500/20 shadow-xl space-y-4">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div>
                  <h3 className="text-sm font-bold text-white tracking-tight flex items-center gap-2">
                    <Database className="w-4 h-4 text-[#ff6600]" />
                    Every Document Available in OpenKB API ({allDocs.length})
                  </h3>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Click any document or use the right tick box to open and inspect the full document in another tab.
                  </p>
                </div>
                <span className="text-xs text-[#ff6600] font-mono">
                  Multi-Source Catalog
                </span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs text-gray-300">
                  <thead className="bg-[#050508] text-gray-400 uppercase font-mono text-[10px] border-b border-white/5">
                    <tr>
                      <th className="py-3 px-3">Document Title</th>
                      <th className="py-3 px-3">Symbol</th>
                      <th className="py-3 px-3">Category</th>
                      <th className="py-3 px-3">Size</th>
                      <th className="py-3 px-3">Ingestion Status</th>
                      <th className="py-3 px-3 text-right">View in Tab</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {allDocs
                      .filter(d => 
                        !docSearch || 
                        d.name.toLowerCase().includes(docSearch.toLowerCase()) || 
                        d.symbol.toLowerCase().includes(docSearch.toLowerCase())
                      )
                      .map((doc, idx) => {
                        const openDocUrl = doc.view_url || `/api/documents/view?name=${encodeURIComponent(doc.file_name || doc.name)}`;
                        return (
                          <tr 
                            key={idx} 
                            onClick={() => window.open(openDocUrl, '_blank')}
                            className="hover:bg-white/[0.04] transition-colors cursor-pointer group"
                          >
                            <td className="py-3 px-3 font-medium text-white flex items-center gap-2">
                              <FileText className={`w-3.5 h-3.5 flex-shrink-0 ${doc.ingested ? 'text-[#ff6600]' : 'text-amber-400'}`} />
                              <span className="truncate max-w-sm group-hover:text-[#ff6600] transition-colors">{doc.name}</span>
                            </td>
                            <td className="py-3 px-3 font-mono font-bold text-[#ff6600]">
                              {doc.symbol}
                            </td>
                            <td className="py-3 px-3 text-gray-400">
                              {doc.doc_type}
                            </td>
                            <td className="py-3 px-3 font-mono text-gray-400">
                              {doc.size_kb} KB
                            </td>
                            <td className="py-3 px-3">
                              {doc.ingested ? (
                                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                                  <CheckCircle className="w-2.5 h-2.5" />
                                  Live & Indexed
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/10 text-amber-300 border border-amber-500/30">
                                  <Clock className="w-2.5 h-2.5" />
                                  Pending Ingest
                                </span>
                              )}
                            </td>
                            <td className="py-3 px-3 text-right">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  window.open(openDocUrl, '_blank');
                                }}
                                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-orange-500/15 hover:bg-orange-500/30 border border-orange-500/35 hover:border-[#ff6600] text-[#ff6600] hover:text-white text-xs font-semibold transition-all group-hover:bg-[#ff6600] group-hover:text-white shadow-sm glow-orange-sm cursor-pointer"
                                title="Open document in new tab"
                              >
                                <CheckSquare className="w-3.5 h-3.5" />
                                <span>Open</span>
                                <ExternalLink className="w-3 h-3 opacity-80" />
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* TAB 2: PENDING DOCUMENTS TABLE */}
          {docFilterTab === 'pending' && (
            <div className="p-6 rounded-2xl bg-[#0c0d14] border border-amber-500/20 shadow-xl space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-bold text-white tracking-tight flex items-center gap-2">
                    <Clock className="w-4 h-4 text-amber-400" />
                    Available Raw Documents Waiting for Ingestion ({pendingDocs.length})
                  </h3>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Click radio to select for ingestion, or click document / right tick box to open in another tab.
                  </p>
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs text-gray-300">
                  <thead className="bg-[#050508] text-gray-400 uppercase font-mono text-[10px] border-b border-white/5">
                    <tr>
                      <th className="py-3 px-3">Select</th>
                      <th className="py-3 px-3">Document File</th>
                      <th className="py-3 px-3">Symbol</th>
                      <th className="py-3 px-3">Detected Category</th>
                      <th className="py-3 px-3">Size</th>
                      <th className="py-3 px-3">Status</th>
                      <th className="py-3 px-3 text-right">View in Tab</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {pendingDocs
                      .filter(d => 
                        !docSearch || 
                        d.name.toLowerCase().includes(docSearch.toLowerCase()) || 
                        d.symbol.toLowerCase().includes(docSearch.toLowerCase())
                      )
                      .map((doc, idx) => {
                        const isSelected = selectedPendingDoc?.file_name === doc.file_name;
                        const openDocUrl = doc.view_url || `/api/documents/view?name=${encodeURIComponent(doc.file_name || doc.name)}`;
                        return (
                          <tr 
                            key={idx} 
                            onClick={() => setSelectedPendingDoc(doc)}
                            className={`cursor-pointer transition-colors ${
                              isSelected ? 'bg-amber-500/15 border-l-2 border-amber-400' : 'hover:bg-white/[0.04]'
                            }`}
                          >
                            <td className="py-3 px-3">
                              <input
                                type="radio"
                                name="pending_selection"
                                checked={isSelected}
                                onChange={() => setSelectedPendingDoc(doc)}
                                className="text-[#ff6600] focus:ring-0 cursor-pointer"
                              />
                            </td>
                            <td 
                              onClick={(e) => {
                                e.stopPropagation();
                                window.open(openDocUrl, '_blank');
                              }}
                              className="py-3 px-3 font-medium text-white flex items-center gap-2 hover:text-[#ff6600] transition-colors"
                            >
                              <FileText className="w-3.5 h-3.5 text-amber-400 flex-shrink-0" />
                              <span className="truncate max-w-sm">{doc.name}</span>
                            </td>
                            <td className="py-3 px-3 font-mono font-bold text-[#ff6600]">
                              {doc.symbol}
                            </td>
                            <td className="py-3 px-3 text-gray-400">
                              {doc.doc_type}
                            </td>
                            <td className="py-3 px-3 font-mono text-gray-400">
                              {doc.size_kb} KB
                            </td>
                            <td className="py-3 px-3">
                              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/10 text-amber-300 border border-amber-500/30">
                                <Clock className="w-2.5 h-2.5" />
                                Pending Ingestion
                              </span>
                            </td>
                            <td className="py-3 px-3 text-right">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  window.open(openDocUrl, '_blank');
                                }}
                                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-orange-500/15 hover:bg-orange-500/30 border border-orange-500/35 hover:border-[#ff6600] text-[#ff6600] hover:text-white text-xs font-semibold transition-all shadow-sm glow-orange-sm cursor-pointer"
                                title="Open document in other tab"
                              >
                                <CheckSquare className="w-3.5 h-3.5" />
                                <span>Open</span>
                                <ExternalLink className="w-3 h-3 opacity-80" />
                              </button>
                            </td>
                          </tr>
                        );
                      })}

                    {pendingDocs.length === 0 && (
                      <tr>
                        <td colSpan="7" className="py-8 text-center text-gray-400">
                          🎉 All available documents have already been ingested into OpenKB PageIndex!
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* TAB 3: INGESTED DOCUMENTS TABLE */}
          {docFilterTab === 'ingested' && (
            <div className="p-6 rounded-2xl bg-[#0c0d14] border border-white/10 shadow-xl space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-bold text-white tracking-tight flex items-center gap-2">
                    <CheckCircle className="w-4 h-4 text-emerald-400" />
                    Active Knowledge Base in OpenKB ({ingestedDocs.length})
                  </h3>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Live documents indexed with dense vectors and keyword tables. Click document or right tick box to view.
                  </p>
                </div>
                <span className="text-xs text-[#ff6600] font-mono">
                  PageIndex™ Hybrid Ready
                </span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs text-gray-300">
                  <thead className="bg-[#050508] text-gray-400 uppercase font-mono text-[10px] border-b border-white/5">
                    <tr>
                      <th className="py-3 px-3">Document Title</th>
                      <th className="py-3 px-3">Symbol</th>
                      <th className="py-3 px-3">Category</th>
                      <th className="py-3 px-3">Size</th>
                      <th className="py-3 px-3">Status</th>
                      <th className="py-3 px-3 text-right">View in Tab</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {ingestedDocs
                      .filter(d => 
                        !docSearch || 
                        d.name.toLowerCase().includes(docSearch.toLowerCase()) || 
                        d.symbol.toLowerCase().includes(docSearch.toLowerCase())
                      )
                      .map((doc, idx) => {
                        const openDocUrl = doc.view_url || `/api/documents/view?name=${encodeURIComponent(doc.file_name || doc.name)}`;
                        return (
                          <tr 
                            key={idx} 
                            onClick={() => window.open(openDocUrl, '_blank')}
                            className="hover:bg-white/[0.04] transition-colors cursor-pointer group"
                          >
                            <td className="py-3 px-3 font-medium text-white flex items-center gap-2">
                              <FileText className="w-3.5 h-3.5 text-[#ff6600] flex-shrink-0" />
                              <span className="truncate max-w-sm group-hover:text-[#ff6600] transition-colors">{doc.name}</span>
                            </td>
                            <td className="py-3 px-3 font-mono font-bold text-[#ff6600]">
                              {doc.symbol}
                            </td>
                            <td className="py-3 px-3 text-gray-400">
                              {doc.doc_type}
                            </td>
                            <td className="py-3 px-3 font-mono text-gray-400">
                              {doc.size_kb} KB
                            </td>
                            <td className="py-3 px-3">
                              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                                <CheckCircle className="w-2.5 h-2.5" />
                                Live & Indexed
                              </span>
                            </td>
                            <td className="py-3 px-3 text-right">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  window.open(openDocUrl, '_blank');
                                }}
                                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-orange-500/15 hover:bg-orange-500/30 border border-orange-500/35 hover:border-[#ff6600] text-[#ff6600] hover:text-white text-xs font-semibold transition-all group-hover:bg-[#ff6600] group-hover:text-white shadow-sm glow-orange-sm cursor-pointer"
                                title="Open document in other tab"
                              >
                                <CheckSquare className="w-3.5 h-3.5" />
                                <span>Open</span>
                                <ExternalLink className="w-3 h-3 opacity-80" />
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Upload Custom File */}
          <div className="p-6 rounded-2xl bg-[#0c0d14] border border-white/10 shadow-xl space-y-4">
            <div className="flex items-center gap-2 text-[#ff6600] font-semibold text-sm">
              <UploadCloud className="w-4 h-4" />
              Upload Fresh Document File Directly (PDF / Markdown)
            </div>

            {uploadMsg && (
              <div className={`p-3 rounded-xl border text-xs flex items-center gap-2 ${
                uploadMsg.type === 'success' 
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' 
                  : 'bg-red-500/10 border-red-500/30 text-red-400'
              }`}>
                <CheckCircle className="w-4 h-4 flex-shrink-0" />
                <span>{uploadMsg.text}</span>
              </div>
            )}

            <form onSubmit={handleUpload} className="grid grid-cols-1 md:grid-cols-4 gap-4 items-end">
              <div>
                <label className="block text-xs font-medium text-gray-300 mb-1">Company Symbol</label>
                <select
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value)}
                  className="w-full px-3 py-2 bg-[#050508] border border-white/10 rounded-xl text-xs text-white focus:outline-none focus:border-[#ff6600]"
                >
                  <option value="HAL">HAL — Hindustan Aeronautics Limited</option>
                  <option value="APOLLO">APOLLO — Apollo Micro Systems</option>
                  <option value="BEL">BEL — Bharat Electronics</option>
                  <option value="RELIANCE">RELIANCE — Reliance Industries</option>
                  <option value="TCS">TCS — Tata Consultancy Services</option>
                  <option value="GENERAL">GENERAL — Other Market Filing</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-300 mb-1">Category</label>
                <select
                  value={docType}
                  onChange={(e) => setDocType(e.target.value)}
                  className="w-full px-3 py-2 bg-[#050508] border border-white/10 rounded-xl text-xs text-white focus:outline-none focus:border-[#ff6600]"
                >
                  <option value="annual_report">Annual Report</option>
                  <option value="concall">Concall Transcript</option>
                  <option value="investor_presentation">Investor Presentation</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-300 mb-1">Select File</label>
                <input
                  id="file-upload-input"
                  type="file"
                  accept=".pdf,.md,.txt"
                  required
                  onChange={(e) => setSelectedFile(e.target.files[0])}
                  className="w-full text-xs text-gray-400 file:mr-2 file:py-1.5 file:px-2.5 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-[#ff6600] file:text-white hover:file:bg-[#e65c00] cursor-pointer bg-[#050508] p-1.5 rounded-xl border border-white/10"
                />
              </div>

              <div>
                <button
                  type="submit"
                  disabled={uploading || !selectedFile}
                  className="w-full py-2.5 rounded-xl bg-[#ff6600] hover:bg-[#e65c00] text-white font-semibold text-xs transition-all shadow-md glow-orange-sm flex items-center justify-center gap-2 disabled:opacity-50"
                >
                  {uploading ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      Ingesting...
                    </>
                  ) : (
                    <>
                      <UploadCloud className="w-4 h-4" />
                      Upload & Ingest
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>

        </div>
      )}

      {/* SECTION 2: WHATSAPP WATCHLISTS & CONCALL ALERTS */}
      {adminSection === 'watchlists' && (
        <div className="space-y-6">
          
          {broadcastMsg && (
            <div className={`p-4 rounded-xl border text-xs flex items-center gap-2 ${
              broadcastMsg.type === 'success' 
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' 
                : 'bg-red-500/10 border-red-500/30 text-red-400'
            }`}>
              <CheckCircle className="w-4 h-4 flex-shrink-0" />
              <span>{broadcastMsg.text}</span>
            </div>
          )}

          {/* Corporate Calendar & Meeting Alerts */}
          <div className="p-6 rounded-2xl bg-[#0c0d14] border border-white/10 shadow-xl space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-white/5">
              <div>
                <div className="flex items-center gap-2">
                  <Calendar className="w-4 h-4 text-[#ff6600]" />
                  <h3 className="text-sm font-bold text-white tracking-tight">
                    Corporate Concall & Earnings Meeting Calendar
                  </h3>
                </div>
                <p className="text-xs text-gray-400 mt-0.5">
                  Track upcoming and conducted management meets. Broadcast automated alerts to WhatsApp watchers.
                </p>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-gray-300">
                <thead className="bg-[#050508] text-gray-400 uppercase font-mono text-[10px] border-b border-white/5">
                  <tr>
                    <th className="py-3 px-3">Company</th>
                    <th className="py-3 px-3">Meeting Event</th>
                    <th className="py-3 px-3">Scheduled Date</th>
                    <th className="py-3 px-3">Meeting Status</th>
                    <th className="py-3 px-3">Publication Status</th>
                    <th className="py-3 px-3 text-right">WhatsApp Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {calendarEvents.map((ev, idx) => (
                    <tr key={idx} className="hover:bg-white/[0.02] transition-colors">
                      <td className="py-3 px-3 font-semibold text-white">
                        <span className="text-[#ff6600] font-mono mr-1.5 font-bold">[{ev.symbol}]</span>
                        {ev.company_name}
                      </td>
                      <td className="py-3 px-3 text-gray-300">
                        {ev.event_type} ({ev.fiscal_period})
                      </td>
                      <td className="py-3 px-3 font-mono text-gray-400">
                        {ev.scheduled_date} {ev.scheduled_time}
                      </td>
                      <td className="py-3 px-3">
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${
                          ev.meeting_status === 'Conducted' 
                            ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' 
                            : 'bg-amber-500/10 text-amber-300 border-amber-500/20'
                        }`}>
                          {ev.meeting_status}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-xs font-mono text-gray-400">
                        {ev.published_status}
                      </td>
                      <td className="py-3 px-3 text-right">
                        <button
                          onClick={() => handleBroadcastAlert(ev)}
                          disabled={broadcasting}
                          className="px-3 py-1.5 rounded-lg bg-orange-500/15 hover:bg-orange-500/25 border border-orange-500/40 text-[#ff6600] text-xs font-semibold inline-flex items-center gap-1.5 transition-colors disabled:opacity-50"
                        >
                          <Bell className="w-3 h-3" />
                          Notify Watchers
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* User Watchlists Table */}
          <div className="p-6 rounded-2xl bg-[#0c0d14] border border-white/10 shadow-xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-white/5">
              <div>
                <h3 className="text-sm font-bold text-white tracking-tight flex items-center gap-2">
                  <Users className="w-4 h-4 text-[#ff6600]" />
                  Active WhatsApp User Watchlists ({watchlists.length})
                </h3>
                <p className="text-xs text-gray-400 mt-0.5">
                  Phone numbers subscribed to concall schedule notifications and report releases.
                </p>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-gray-300">
                <thead className="bg-[#050508] text-gray-400 uppercase font-mono text-[10px] border-b border-white/5">
                  <tr>
                    <th className="py-3 px-3">User Phone</th>
                    <th className="py-3 px-3">Tracked Equity Watchlist</th>
                    <th className="py-3 px-3">Notification Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {watchlists.map((w, idx) => (
                    <tr key={idx} className="hover:bg-white/[0.02] transition-colors">
                      <td className="py-3 px-3 font-mono font-semibold text-white flex items-center gap-2">
                        <Smartphone className="w-3.5 h-3.5 text-gray-400" />
                        +{w.phone}
                      </td>
                      <td className="py-3 px-3">
                        <div className="flex flex-wrap gap-1.5">
                          {w.symbols?.map((sym, sIdx) => (
                            <span
                              key={sIdx}
                              className="px-2 py-0.5 rounded-md bg-orange-500/15 text-[#ff6600] border border-orange-500/30 font-mono text-xs font-bold"
                            >
                              {sym}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="py-3 px-3">
                        <span className="inline-flex items-center gap-1 text-[11px] text-emerald-400">
                          <CheckCircle className="w-3 h-3" />
                          Alerts Enabled
                        </span>
                      </td>
                    </tr>
                  ))}

                  {watchlists.length === 0 && (
                    <tr>
                      <td colSpan="3" className="py-8 text-center text-gray-500">
                        No WhatsApp users have created a watchlist yet. Users can send `track HAL` on WhatsApp to start tracking.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

          </div>

          {/* Web Users Watchlists Table */}
          <div className="p-6 rounded-2xl bg-[#0c0d14] border border-white/10 shadow-xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-white/5">
              <div>
                <h3 className="text-sm font-bold text-white tracking-tight flex items-center gap-2">
                  <ShieldCheck className="w-4 h-4 text-[#ff6600]" />
                  Institutional Web User Watchlists ({Object.keys(webWatchlists).length})
                </h3>
                <p className="text-xs text-gray-400 mt-0.5">
                  Web terminal accounts tracking corporate earnings concalls and annual reports.
                </p>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-gray-300">
                <thead className="bg-[#050508] text-gray-400 uppercase font-mono text-[10px] border-b border-white/5">
                  <tr>
                    <th className="py-3 px-3">Username</th>
                    <th className="py-3 px-3">Tracked Equity Watchlist</th>
                    <th className="py-3 px-3">Sync Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {Object.entries(webWatchlists).map(([uname, syms], idx) => (
                    <tr key={idx} className="hover:bg-white/[0.02] transition-colors">
                      <td className="py-3 px-3 font-mono font-semibold text-white flex items-center gap-2">
                        <span className="w-6 h-6 rounded-full bg-orange-500/20 text-[#ff6600] flex items-center justify-center text-[10px] font-bold">
                          {uname[0]?.toUpperCase()}
                        </span>
                        {uname}
                      </td>
                      <td className="py-3 px-3">
                        <div className="flex flex-wrap gap-1.5">
                          {syms?.map((sym, sIdx) => (
                            <span
                              key={sIdx}
                              className="px-2 py-0.5 rounded-md bg-orange-500/15 text-[#ff6600] border border-orange-500/30 font-mono text-xs font-bold"
                            >
                              {sym}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="py-3 px-3">
                        <span className="inline-flex items-center gap-1 text-[11px] text-emerald-400 font-mono">
                          <CheckCircle className="w-3 h-3" />
                          Cloud Synced
                        </span>
                      </td>
                    </tr>
                  ))}

                  {Object.keys(webWatchlists).length === 0 && (
                    <tr>
                      <td colSpan="3" className="py-8 text-center text-gray-500">
                        No web users have added stocks to their watchlist yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

          </div>

        </div>
      )}

      {/* SECTION 3: WHATSAPP USER CREDITS & TOKEN LIMITS */}
      {adminSection === 'credits' && (
        <div className="p-6 rounded-2xl bg-[#0c0d14] border border-white/10 shadow-xl space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-white/5">
            <div>
              <div className="flex items-center gap-2">
                <Coins className="w-4 h-4 text-[#ff6600]" />
                <h3 className="text-sm font-bold text-white tracking-tight">
                  WhatsApp User Credits & Token Quota System
                </h3>
              </div>
              <p className="text-xs text-gray-400 mt-0.5">
                Protects Groq free-tier limits by capping daily token consumption per phone number.
              </p>
            </div>
            <span className="text-xs px-2.5 py-1 rounded-lg bg-orange-500/10 border border-orange-500/30 text-[#ff6600] font-mono">
              Default Limit: 10,000 tokens/day
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-gray-300">
              <thead className="bg-[#050508] text-gray-400 uppercase font-mono text-[10px] border-b border-white/5">
                <tr>
                  <th className="py-3 px-3">Phone Number</th>
                  <th className="py-3 px-3">Daily Quota Used</th>
                  <th className="py-3 px-3">Usage Progress</th>
                  <th className="py-3 px-3">Queries Today</th>
                  <th className="py-3 px-3">VIP Whitelist</th>
                  <th className="py-3 px-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {waUsers.map((u, idx) => {
                  const limit = u.daily_limit || 10000;
                  const used = u.tokens_used_today || 0;
                  const pct = Math.min(100, Math.round((used / limit) * 100));
                  const isWhitelisted = u.is_whitelisted;

                  return (
                    <tr key={idx} className="hover:bg-white/[0.02] transition-colors">
                      <td className="py-3 px-3 font-mono font-semibold text-white flex items-center gap-2">
                        <Smartphone className="w-3.5 h-3.5 text-gray-400" />
                        +{u.phone}
                      </td>

                      <td className="py-3 px-3 font-mono">
                        <span className="text-white font-bold">{used.toLocaleString()}</span>
                        <span className="text-gray-500"> / {limit.toLocaleString()} tokens</span>
                      </td>

                      <td className="py-3 px-3">
                        <div className="w-32 bg-white/5 rounded-full h-1.5 overflow-hidden">
                          <div
                            className={`h-full ${
                              pct > 90 ? 'bg-red-500' : (pct > 60 ? 'bg-amber-500' : 'bg-[#ff6600]')
                            }`}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="text-[10px] text-gray-500 font-mono mt-0.5 block">
                          {pct}% consumed
                        </span>
                      </td>

                      <td className="py-3 px-3 font-mono text-gray-300">
                        {u.queries_today || 0} queries
                      </td>

                      <td className="py-3 px-3">
                        {isWhitelisted ? (
                          <span className="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono text-[10px] font-bold">
                            VIP Whitelisted
                          </span>
                        ) : (
                          <span className="text-gray-500 font-mono text-[10px]">
                            Standard Limit
                          </span>
                        )}
                      </td>

                      <td className="py-3 px-3 text-right">
                        {editingPhone === u.phone ? (
                          <div className="flex items-center justify-end gap-2">
                            <input
                              type="number"
                              value={editLimitVal}
                              onChange={(e) => setEditLimitVal(e.target.value)}
                              className="w-20 px-2 py-1 bg-[#050508] border border-white/20 rounded text-xs text-white"
                            />
                            <label className="flex items-center gap-1 text-[10px] text-gray-400">
                              <input
                                type="checkbox"
                                checked={editWhitelistVal}
                                onChange={(e) => setEditWhitelistVal(e.target.checked)}
                              />
                              VIP
                            </label>
                            <button
                              onClick={() => handleSaveWaLimit(u.phone)}
                              className="px-2 py-1 rounded bg-[#ff6600] text-white text-[10px] font-semibold"
                            >
                              Save
                            </button>
                            <button
                              onClick={() => setEditingPhone(null)}
                              className="px-2 py-1 rounded bg-white/10 text-gray-300 text-[10px]"
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <button
                            onClick={() => {
                              setEditingPhone(u.phone);
                              setEditLimitVal(u.daily_limit || 10000);
                              setEditWhitelistVal(u.is_whitelisted || false);
                            }}
                            className="px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-gray-300 text-xs font-medium flex items-center gap-1 ml-auto"
                          >
                            <Edit2 className="w-3 h-3" />
                            Adjust Limit
                          </button>
                        )}
                      </td>

                    </tr>
                  );
                })}

                {waUsers.length === 0 && (
                  <tr>
                    <td colSpan="6" className="py-8 text-center text-gray-500">
                      No active WhatsApp users tracked yet. Incoming queries via webhook will appear here with quota usage.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

    </div>
  );
}

import React from 'react';
import { 
  ShieldCheck, 
  User, 
  LogOut, 
  LogIn, 
  Cpu, 
  Zap, 
  Terminal, 
  Database, 
  Layers 
} from 'lucide-react';

export default function Navbar({ 
  currentUser, 
  activeTab, 
  setActiveTab, 
  onOpenAuth, 
  onLogout,
  selectedProvider,
  setSelectedProvider
}) {
  const isAdmin = currentUser?.role === 'admin';

  return (
    <header className="sticky top-0 z-40 w-full border-b border-orange-500/20 bg-[#050508]/90 backdrop-blur-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        
        {/* Brand / Logo */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-[#ff6600] to-[#b34700] p-0.5 flex items-center justify-center glow-orange-sm shadow-lg">
            <div className="w-full h-full bg-[#050508] rounded-[7px] flex items-center justify-center">
              <Zap className="w-5 h-5 text-[#ff6600]" />
            </div>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-lg font-bold tracking-tight text-white">FINCEPT</span>
              <span className="text-xs font-semibold px-1.5 py-0.5 rounded bg-orange-500/15 text-[#ff6600] border border-orange-500/30">
                NIFTY RAG
              </span>
            </div>
            <p className="text-[10px] text-gray-400 -mt-0.5 tracking-wider uppercase font-medium">
              Institutional Equity Intelligence
            </p>
          </div>
        </div>

        {/* View Switcher Tabs (If Admin, show toggle; if User, show indicator) */}
        <div className="hidden md:flex items-center gap-2 bg-[#0c0d14] p-1 rounded-xl border border-white/5">
          <button
            onClick={() => setActiveTab('chat')}
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeTab === 'chat'
                ? 'bg-[#ff6600] text-white shadow-md glow-orange-sm'
                : 'text-gray-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <Terminal className="w-3.5 h-3.5" />
            Research Terminal
          </button>

          {isAdmin ? (
            <button
              onClick={() => setActiveTab('admin')}
              className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
                activeTab === 'admin'
                  ? 'bg-[#ff6600] text-white shadow-md glow-orange-sm'
                  : 'text-gray-400 hover:text-white hover:bg-white/5'
              }`}
            >
              <Database className="w-3.5 h-3.5" />
              Admin Portal
              <span className="px-1.5 py-0.2 rounded text-[9px] bg-black/40 text-orange-200 border border-white/10 uppercase font-bold">
                PRO
              </span>
            </button>
          ) : (
            <div className="flex items-center gap-1.5 px-3 py-1 text-[11px] text-gray-500 font-mono">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
              User Mode
            </div>
          )}
        </div>

        {/* Right Section: Model Selector & Auth */}
        <div className="flex items-center gap-3">
          {/* Provider selector */}
          <div className="hidden sm:flex items-center gap-1.5 bg-[#0c0d14] border border-white/10 rounded-lg px-2.5 py-1">
            <Cpu className="w-3.5 h-3.5 text-[#ff6600]" />
            <select
              value={selectedProvider}
              onChange={(e) => setSelectedProvider(e.target.value)}
              className="bg-transparent text-xs text-gray-200 focus:outline-none cursor-pointer pr-1"
            >
              <option value="auto" className="bg-[#0c0d14] text-white">Parallel RAG (Fast 2s)</option>
              <option value="groq-llama" className="bg-[#0c0d14] text-white">Groq LLaMA 3.3 70B</option>
              <option value="or-qwen30b" className="bg-[#0c0d14] text-white">Qwen 2.5 72B</option>
              <option value="gemini" className="bg-[#0c0d14] text-white">Google Gemini 2.5</option>
            </select>
          </div>

          {/* User Status / Login */}
          {currentUser ? (
            <div className="flex items-center gap-2.5">
              <div className="hidden sm:flex flex-col text-right">
                <span className="text-xs font-semibold text-white leading-tight">
                  {currentUser.name || currentUser.username}
                </span>
                <span className={`text-[10px] uppercase font-mono font-bold ${
                  currentUser.role === 'admin' ? 'text-[#ff6600]' : 'text-emerald-400'
                }`}>
                  {currentUser.role}
                </span>
              </div>
              <button
                onClick={onLogout}
                title="Sign Out"
                className="p-2 rounded-lg bg-white/5 hover:bg-red-500/10 text-gray-300 hover:text-red-400 border border-white/5 transition-colors"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </div>
          ) : (
            <button
              onClick={onOpenAuth}
              className="flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-[#ff6600] hover:bg-[#e65c00] text-white text-xs font-semibold transition-all shadow-md glow-orange-sm"
            >
              <LogIn className="w-3.5 h-3.5" />
              Sign In
            </button>
          )}

        </div>

      </div>
    </header>
  );
}
